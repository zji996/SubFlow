"""LLM ASR correction stage (compare merged ASR vs segmented ASR)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast

from subflow.exceptions import StageExecutionError
from subflow.models.segment import ASRCorrectedSegment, ASRMergedChunk, ASRSegment
from subflow.pipeline.context import PipelineContext, ProgressReporter
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
            "2. 只纠正听错字（谐音字、漏字、多字）\n"
            "3. 删除明显的 ASR 幻觉\n"
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

        # Fallback if no API key
        if not self.api_key:
            logger.info("llm_asr_correction fallback (no api key, profile=%s)", self.profile)
            context["asr_corrected_segments"] = {
                seg.id: ASRCorrectedSegment(id=seg.id, asr_segment_id=seg.id, text=seg.text)
                for seg in asr_segments
            }
            context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
            return context

        asr_by_id: dict[int, ASRSegment] = {int(seg.id): seg for seg in asr_segments}
        corrected: dict[int, ASRCorrectedSegment] = {}

        logger.info(
            "llm_asr_correction start (merged_chunks=%d, profile=%s, concurrency=%d)",
            len(merged_chunks),
            self.profile,
            int(self.settings.concurrency_llm_correction),
        )
        system_prompt = self._get_system_prompt()

        semaphore = asyncio.Semaphore(max(1, int(self.settings.concurrency_llm_correction)))

        async def _process_chunk(chunk: ASRMergedChunk) -> dict[int, str]:
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
                return {}

            user_input = self._build_user_input(merged_text=chunk.text, segmented=seg_payload)
            async with semaphore:
                result = await self.json_helper.complete_json(
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
            return out

        total_chunks = len(merged_chunks)
        if progress_reporter and total_chunks > 0:
            await progress_reporter.report(0, f"纠错中 0/{total_chunks} 区域")

        done_chunks = 0
        tasks = [asyncio.create_task(_process_chunk(c)) for c in merged_chunks]
        for fut in asyncio.as_completed(tasks):
            updates = await fut
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
            if progress_reporter and total_chunks > 0:
                pct = int(done_chunks / total_chunks * 100)
                await progress_reporter.report(pct, f"纠错中 {done_chunks}/{total_chunks} 区域")

        # Ensure we keep a complete corrected view for downstream export.
        for seg in asr_segments:
            existing = corrected.get(seg.id)
            if existing is None:
                corrected[seg.id] = ASRCorrectedSegment(id=seg.id, asr_segment_id=seg.id, text=seg.text)
            elif not existing.text:
                existing.text = seg.text

        context["asr_segments"] = asr_segments
        context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
        context["asr_corrected_segments"] = corrected
        context["full_transcript"] = " ".join(seg.text for seg in asr_segments if (seg.text or "").strip())
        logger.info("llm_asr_correction done (corrected_segments=%d)", len(corrected))
        return context
