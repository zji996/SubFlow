"""LLM ASR correction stage (compare merged ASR vs segmented ASR)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast

from subflow.exceptions import ConfigurationError, StageExecutionError
from subflow.models.segment import ASRCorrectedSegment, ASRMergedChunk, ASRSegment
from subflow.pipeline.concurrency import ServiceType, get_concurrency_tracker
from subflow.pipeline.context import MetricsProgressReporter, PipelineContext, ProgressReporter
from subflow.providers.llm import Message
from subflow.stages.base_llm import BaseLLMStage

logger = logging.getLogger(__name__)


class LLMASRCorrectionStage(BaseLLMStage):
    name = "llm_asr_correction"
    profile_attr = "asr_correction"

    def validate_input(self, context: PipelineContext) -> bool:
        return bool(context.get("asr_segments"))

    @staticmethod
    def _get_system_prompt() -> str:
        return (
            "你是语音识别纠错助手。对比完整识别和分段识别，纠正分段识别的错误。\n\n"
            "输入说明：\n"
            "- 【完整识别】: 对合并音频整体识别的结果，上下文完整\n"
            "- 【分段识别】: 对每小段音频单独识别的结果\n\n"
            "规则：\n"
            "1. 以【完整识别】为参考，纠正【分段识别】中的错误\n"
            "2. 只纠正听错字（谐音字、漏字、多字），不要改写句子风格\n"
            "3. 幻觉检测与删除（只删除明显幻觉，不确定就保留）：\n"
            "   - 跨语言幻觉：中文语境中突然出现完整英文句子（或反之），且与上下文不一致 → 删除\n"
            "   - 主题脱节幻觉：突然出现与上下文无关的模式化语料（如 “please subscribe/thank you for watching/transcribe/written format”）→ 删除\n"
            "   - 重复幻觉：同一内容用不同语言重复出现，通常幻觉版本只出现在【分段识别】→ 删除幻觉版本\n"
            "   - 识别技巧：如果某内容只在【分段识别】出现，但【完整识别】没有 → 高概率是幻觉\n"
            "4. 保持分段边界不变，按 id 返回\n\n"
            "输出 JSON（只输出需要纠正的段落）：\n"
            "[\n"
            '  {"id": 0, "text": "纠正后文本"}\n'
            "]\n"
            "无需纠正则返回空数组 []"
        )

    @staticmethod
    def _build_user_input(*, merged_text: str, segmented: list[dict[str, Any]]) -> str:
        parts = [
            "【完整识别】",
            (merged_text or "").strip(),
            "",
            "【分段识别】",
            json.dumps(segmented, ensure_ascii=False),
        ]
        return "\n".join(parts).strip()

    async def execute(
        self,
        context: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> PipelineContext:
        context = cast(PipelineContext, dict(context))
        asr_segments: list[ASRSegment] = list(context.get("asr_segments") or [])
        merged_chunks: list[ASRMergedChunk] = list(context.get("asr_merged_chunks") or [])

        if not self.api_key:
            profile = str(self.profile or "").strip().lower() or "fast"
            env_key = "LLM_POWER_API_KEY" if profile == "power" else "LLM_FAST_API_KEY"
            raise ConfigurationError(
                f"{self.name} requires LLM api_key (profile={profile}); set {env_key}"
            )

        asr_by_id: dict[int, ASRSegment] = {int(seg.id): seg for seg in asr_segments}
        corrected: dict[int, ASRCorrectedSegment] = {}
        concurrency = max(1, int(self.get_concurrency_limit(self.settings)))
        service: ServiceType = (
            "llm_power" if str(self.profile or "").strip().lower() == "power" else "llm_fast"
        )
        tracker = get_concurrency_tracker(self.settings)
        started_at = time.monotonic()
        llm_prompt_tokens = 0
        llm_completion_tokens = 0
        llm_calls = 0

        logger.info(
            "llm_asr_correction start (merged_chunks=%d, profile=%s, concurrency=%d)",
            len(merged_chunks),
            self.profile,
            concurrency,
        )
        system_prompt = self._get_system_prompt()

        async def _complete_json(messages: list[Message]) -> tuple[Any, object | None]:
            helper = self.json_helper
            complete_with_usage = getattr(helper, "complete_json_with_usage", None)
            if callable(complete_with_usage):
                fn = cast(
                    Callable[[list[Message]], Awaitable[tuple[Any, object]]],
                    complete_with_usage,
                )
                return await fn(messages)
            return await helper.complete_json(messages), None

        async def _process_chunk(chunk: ASRMergedChunk) -> tuple[dict[int, str], object | None]:
            seg_payload: list[dict[str, Any]] = []
            allowed_ids: set[int] = set()
            for seg_id in list(chunk.segment_ids or []):
                seg = asr_by_id.get(int(seg_id))
                if seg is None:
                    continue
                sid = int(seg.id)
                allowed_ids.add(sid)
                seg_payload.append({"id": sid, "text": str(seg.text or "")})

            if not seg_payload:
                return {}, None

            user_input = self._build_user_input(merged_text=chunk.text, segmented=seg_payload)
            async with tracker.acquire(service):
                result, usage = await _complete_json(
                    [
                        Message(role="system", content=system_prompt),
                        Message(role="user", content=user_input),
                    ]
                )

            if not isinstance(result, list):
                raise StageExecutionError(self.name, "ASR correction output must be a JSON array")

            out: dict[int, str] = {}
            for item in result:
                if not isinstance(item, dict):
                    continue
                raw_id = item.get("id")
                if raw_id is None:
                    continue
                try:
                    seg_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if seg_id not in allowed_ids:
                    continue
                seg = asr_by_id.get(seg_id)
                if seg is None:
                    continue
                new_text = str(item.get("text") or "").strip()
                out[seg_id] = new_text
            return out, usage

        total_chunks = len(merged_chunks)
        if progress_reporter and total_chunks > 0:
            if isinstance(progress_reporter, MetricsProgressReporter):
                state = await tracker.snapshot(service)
                await progress_reporter.report_metrics(
                    {
                        "progress": 0,
                        "progress_message": f"纠错中 0/{total_chunks} 块",
                        "items_processed": 0,
                        "items_total": int(total_chunks),
                        "items_per_second": 0.0,
                        "active_tasks": int(state.active),
                        "max_concurrent": int(state.max),
                    }
                )
            else:
                await progress_reporter.report(0, f"纠错中 0/{total_chunks} 块")

        done_chunks = 0
        ordered_chunks = sorted(
            merged_chunks,
            key=lambda c: (float(c.start), float(c.end), int(c.region_id), int(c.chunk_id)),
        )
        tasks = [asyncio.create_task(_process_chunk(c)) for c in ordered_chunks]

        for fut in asyncio.as_completed(tasks):
            updates, usage = await fut
            for seg_id, new_text in updates.items():
                seg = asr_by_id.get(int(seg_id))
                if seg is None:
                    continue
                seg.text = str(new_text or "").strip()
                corrected[int(seg_id)] = ASRCorrectedSegment(
                    id=int(seg_id),
                    asr_segment_id=int(seg_id),
                    text=str(new_text or "").strip(),
                )
            done_chunks += 1
            if isinstance(usage, dict):
                prompt = usage.get("prompt_tokens")
                completion = usage.get("completion_tokens")
                if isinstance(prompt, int):
                    llm_prompt_tokens += int(prompt)
                if isinstance(completion, int):
                    llm_completion_tokens += int(completion)
                llm_calls += 1
            else:
                # Best-effort: allow helper to return LLMUsage dataclass.
                prompt = getattr(usage, "prompt_tokens", None)
                completion = getattr(usage, "completion_tokens", None)
                if isinstance(prompt, int):
                    llm_prompt_tokens += int(prompt)
                if isinstance(completion, int):
                    llm_completion_tokens += int(completion)
                if usage is not None:
                    llm_calls += 1
            if progress_reporter and total_chunks > 0:
                pct = int(done_chunks / total_chunks * 100)
                msg = f"纠错中 {done_chunks}/{total_chunks} 块"
                if isinstance(progress_reporter, MetricsProgressReporter):
                    elapsed = max(0.001, time.monotonic() - started_at)
                    state = await tracker.snapshot(service)
                    tokens_total = llm_prompt_tokens + llm_completion_tokens
                    await progress_reporter.report_metrics(
                        {
                            "progress": pct,
                            "progress_message": msg,
                            "items_processed": int(done_chunks),
                            "items_total": int(total_chunks),
                            "items_per_second": float(done_chunks) / elapsed,
                            "llm_prompt_tokens": int(llm_prompt_tokens),
                            "llm_completion_tokens": int(llm_completion_tokens),
                            "llm_calls_count": int(llm_calls),
                            "llm_tokens_per_second": float(tokens_total) / elapsed,
                            "active_tasks": int(state.active),
                            "max_concurrent": int(state.max),
                        }
                    )
                else:
                    await progress_reporter.report(pct, msg)

        # Ensure we keep a complete corrected view for downstream export.
        for seg in asr_segments:
            existing = corrected.get(seg.id)
            if existing is None:
                corrected[seg.id] = ASRCorrectedSegment(
                    id=seg.id, asr_segment_id=seg.id, text=seg.text
                )
            elif not existing.text:
                existing.text = seg.text

        context["asr_segments"] = asr_segments
        context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
        context["asr_corrected_segments"] = corrected
        context["full_transcript"] = " ".join(
            seg.text for seg in asr_segments if (seg.text or "").strip()
        )
        logger.info("llm_asr_correction done (corrected_segments=%d)", len(corrected))
        return context
