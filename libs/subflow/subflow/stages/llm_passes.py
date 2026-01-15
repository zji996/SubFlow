"""LLM passes (global understanding + 1:1 per-segment translation)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, cast

from subflow.exceptions import StageExecutionError
from subflow.models.segment import (
    ASRCorrectedSegment,
    ASRSegment,
    SegmentTranslation,
    SemanticChunk,
)
from subflow.pipeline.concurrency import ServiceType, get_concurrency_tracker
from subflow.pipeline.context import MetricsProgressReporter, PipelineContext, ProgressReporter
from subflow.providers.llm import Message
from subflow.stages.base_llm import BaseLLMStage
from subflow.utils.tokenizer import count_tokens, truncate_to_tokens

logger = logging.getLogger(__name__)


def _compact_global_context(global_context: dict[str, Any] | None) -> dict[str, Any]:
    ctx = dict(global_context or {})
    return {
        "topic": str(ctx.get("topic") or "").strip() or "unknown",
        "domain": str(ctx.get("domain") or "").strip() or "unknown",
        "style": str(ctx.get("style") or "").strip() or "unknown",
        "glossary": dict(ctx.get("glossary") or {}),
        "translation_notes": list(ctx.get("translation_notes") or []),
    }


class GlobalUnderstandingPass(BaseLLMStage):
    """Pass 1: Global understanding with 8000 token limit."""

    name = "llm_global_understanding"
    profile_attr = "global_understanding"

    MAX_TOTAL_TOKENS = 8000
    MAX_TRANSCRIPT_TOKENS = 6000
    SYSTEM_PROMPT_TOKENS = 500

    def validate_input(self, context: PipelineContext) -> bool:
        return bool(context.get("full_transcript"))

    def _get_system_prompt(self) -> str:
        return (
            "你是一个专业的视频内容分析助手。请分析以下视频转录文本，提取：\n"
            "1. 视频主题和领域\n"
            "2. 语言风格 (正式/非正式/技术等)\n"
            "3. 核心术语表 (原文 -> 建议翻译)\n"
            "4. 翻译注意事项（风格、术语一致性、单位/缩写等）\n\n"
            "请用 JSON 格式输出，可以使用 ```json ... ``` 包裹：\n"
            "{\n"
            '  "topic": "视频主题",\n'
            '  "domain": "技术/教育/娱乐/...",\n'
            '  "style": "正式/非正式/技术",\n'
            '  "glossary": {"source_term": "目标翻译"},\n'
            '  "translation_notes": ["注意事项"]\n'
            "}"
        )

    async def execute(
        self,
        context: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> PipelineContext:
        context = cast(PipelineContext, dict(context))
        transcript = str(context.get("full_transcript", "")).strip()
        started_at = time.monotonic()
        service: ServiceType = (
            "llm_power" if str(self.profile or "").strip().lower() == "power" else "llm_fast"
        )
        tracker = get_concurrency_tracker(self.settings)

        if not self.api_key:
            logger.info("llm_global_understanding fallback (no api key, profile=%s)", self.profile)
            context["global_context"] = {
                "topic": "unknown",
                "domain": "unknown",
                "style": "unknown",
                "glossary": {},
                "translation_notes": [],
            }
            return context

        raw_tokens = count_tokens(transcript)
        transcript = truncate_to_tokens(transcript, self.MAX_TRANSCRIPT_TOKENS, strategy="sample")
        logger.info(
            "llm_global_understanding start (tokens=%d->%d, profile=%s)",
            raw_tokens,
            count_tokens(transcript),
            self.profile,
        )

        system_prompt = self._get_system_prompt()

        if progress_reporter is not None:
            if isinstance(progress_reporter, MetricsProgressReporter):
                await progress_reporter.report_metrics(
                    {"progress": 0, "progress_message": "全局理解中"}
                )
            else:
                await progress_reporter.report(0, "全局理解中")

        helper = self.json_helper
        complete_with_usage = getattr(helper, "complete_json_with_usage", None)
        if callable(complete_with_usage):
            async with tracker.acquire(service):
                result, usage = await complete_with_usage(
                    [
                        Message(role="system", content=system_prompt),
                        Message(role="user", content=transcript),
                    ]
                )
        else:
            async with tracker.acquire(service):
                result = await helper.complete_json(
                    [
                        Message(role="system", content=system_prompt),
                        Message(role="user", content=transcript),
                    ]
                )
            usage = None

        if not isinstance(result, dict):
            raise StageExecutionError(
                self.name, "Global understanding output must be a JSON object"
            )

        context["global_context"] = result

        if progress_reporter is not None:
            elapsed = max(0.001, time.monotonic() - started_at)
            state = await tracker.snapshot(service)
            prompt = getattr(usage, "prompt_tokens", None)
            completion = getattr(usage, "completion_tokens", None)
            llm_prompt = int(prompt) if isinstance(prompt, int) else 0
            llm_completion = int(completion) if isinstance(completion, int) else 0
            if isinstance(progress_reporter, MetricsProgressReporter):
                await progress_reporter.report_metrics(
                    {
                        "progress": 100,
                        "progress_message": "全局理解完成",
                        "llm_prompt_tokens": llm_prompt,
                        "llm_completion_tokens": llm_completion,
                        "llm_calls_count": 1 if usage is not None else 0,
                        "llm_tokens_per_second": float(llm_prompt + llm_completion) / elapsed,
                        "active_tasks": int(state.active),
                        "max_concurrent": int(state.max),
                    }
                )
            else:
                await progress_reporter.report(100, "全局理解完成")

        logger.info("llm_global_understanding done")
        return context


class SemanticChunkingPass(BaseLLMStage):
    """Pass 2: Translate each segment 1:1 (no semantic merging)."""

    name = "llm_semantic_chunking"
    profile_attr = "semantic_translation"

    def validate_input(self, context: PipelineContext) -> bool:
        return bool(context.get("asr_segments")) and bool(context.get("target_language"))

    def _get_system_prompt(self) -> str:
        return (
            "你是一位专业的翻译专家。将给定的多个句子翻译成目标语言。\n\n"
            "## 规则\n"
            "1. 意译优先：翻译要通顺自然，传达意思而非逐字翻译\n"
            "2. 适合字幕：简洁明了，适合阅读\n"
            "3. 保持顺序：按输入顺序输出翻译\n\n"
            "## 输入格式\n"
            '每行一个句子，格式为 "[id]: 句子内容"\n\n'
            "## 输出格式\n"
            '每行一个翻译，格式为 "[id]: 翻译内容"\n'
            "只输出这些行，不要其他内容。"
        )

    @staticmethod
    def _group_segments_by_sentence(
        segments: list[ASRSegment],
        *,
        get_text: Any,
        sentence_endings: str,
    ) -> list[list[ASRSegment]]:
        endings = set(str(sentence_endings or ""))
        groups: list[list[ASRSegment]] = []
        current: list[ASRSegment] = []
        for seg in list(segments or []):
            txt = str(get_text(seg) or "").rstrip()
            if not txt:
                continue
            current.append(seg)
            last = txt[-1:]
            if last and last in endings:
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        return groups

    def _build_batch_user_input(
        self,
        *,
        target_language: str,
        global_context: dict[str, Any],
        items: list[tuple[int, str]],
    ) -> str:
        parts: list[str] = [f"目标语言：{target_language}"]
        compact_context = _compact_global_context(global_context)
        if compact_context:
            parts.append(f"全局上下文：\n{json.dumps(compact_context, ensure_ascii=False)}")
        lines: list[str] = []
        for seg_id, text in items:
            lines.append(f"[{int(seg_id)}]: {str(text or '').strip()}")
        parts.append("待翻译：\n" + "\n".join(lines).strip())
        return "\n\n".join(parts).strip()

    @classmethod
    def _parse_batch_translation(cls, raw_text: str, *, expected_ids: list[int]) -> dict[int, str]:
        text = str(raw_text or "").strip()
        if not text:
            raise ValueError("Empty LLM output")

        cleaned: list[str] = []
        for line in text.splitlines():
            if line.strip().startswith("```"):
                continue
            stripped = line.strip()
            if stripped:
                cleaned.append(stripped)

        pattern = re.compile(r"^\[(\d+)\]\s*:\s*(.*)$")
        out: dict[int, str] = {}
        for line in cleaned:
            m = pattern.match(line)
            if not m:
                continue
            seg_id = int(m.group(1))
            if seg_id not in out:
                out[seg_id] = cls._clean_translation(m.group(2))

        if not out:
            sample = "\n".join(cleaned[:5]).strip()
            raise ValueError(f"Unable to parse any [id]: lines from LLM output. Sample:\n{sample}")

        missing = [int(i) for i in expected_ids if int(i) not in out]
        if missing:
            sample = "\n".join(cleaned[:10]).strip()
            raise ValueError(f"Missing translations for ids={missing}. Sample:\n{sample}")

        return out

    @staticmethod
    def _clean_translation(text: str) -> str:
        s = str(text or "").strip()
        if not s:
            return ""
        if s.startswith("```"):
            parts = [line for line in s.splitlines() if not line.strip().startswith("```")]
            s = "\n".join(parts).strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()
        return s.strip()

    async def execute(
        self,
        context: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> PipelineContext:
        context = cast(PipelineContext, dict(context))
        asr_segments: list[ASRSegment] = list(context.get("asr_segments") or [])
        corrected_map: dict[int, ASRCorrectedSegment] = dict(
            context.get("asr_corrected_segments") or {}
        )
        target_language = str(context.get("target_language", "zh") or "zh").strip() or "zh"
        global_ctx = dict(context.get("global_context") or {})

        started_at = time.monotonic()
        llm_prompt_tokens = 0
        llm_completion_tokens = 0
        llm_calls = 0
        tokens_lock = asyncio.Lock()

        service: ServiceType = (
            "llm_power" if str(self.profile or "").strip().lower() == "power" else "llm_fast"
        )
        tracker = get_concurrency_tracker(self.settings)

        ordered = sorted(asr_segments, key=lambda s: (float(s.start), float(s.end), int(s.id)))

        def _src_text(seg: ASRSegment) -> str:
            corrected = corrected_map.get(int(seg.id))
            return str((corrected.text if corrected is not None else seg.text) or "").strip()

        translatable = [seg for seg in ordered if _src_text(seg)]
        total = len(translatable)

        if not self.api_key:
            logger.info("llm_semantic_chunking fallback (no api key, profile=%s)", self.profile)
            translations: list[SegmentTranslation] = []
            chunks: list[SemanticChunk] = []
            for seg in translatable:
                src = _src_text(seg)
                tr = f"[{target_language}] {src}"
                translations.append(
                    SegmentTranslation(segment_id=int(seg.id), source_text=src, translation=tr)
                )
                chunks.append(
                    SemanticChunk(
                        id=int(seg.id),
                        text=src,
                        translation=tr,
                        asr_segment_ids=[int(seg.id)],
                        translation_chunks=[],
                    )
                )
            context["segment_translations"] = translations
            context["semantic_chunks"] = chunks
            context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
            return context

        if progress_reporter and total > 0:
            if isinstance(progress_reporter, MetricsProgressReporter):
                state = await tracker.snapshot(service)
                await progress_reporter.report_metrics(
                    {
                        "progress": 0,
                        "progress_message": f"翻译中 0/{total} 段",
                        "items_processed": 0,
                        "items_total": int(total),
                        "items_per_second": 0.0,
                        "active_tasks": int(state.active),
                        "max_concurrent": int(state.max),
                    }
                )
            else:
                await progress_reporter.report(0, f"翻译中 0/{total} 段")

        system_prompt = self._get_system_prompt()
        batch_size = max(
            1, int(getattr(self.settings.llm_limits, "translation_batch_size", 10) or 10)
        )

        translations: list[SegmentTranslation] = []
        chunks: list[SemanticChunk] = []

        sentence_groups = self._group_segments_by_sentence(
            translatable,
            get_text=_src_text,
            sentence_endings=str(
                getattr(self.settings.greedy_sentence_asr, "sentence_endings", "。？！；?!;.") or ""
            ),
        )

        batches: list[list[ASRSegment]] = []
        current_batch: list[ASRSegment] = []
        for group in sentence_groups:
            if not current_batch:
                if len(group) > batch_size:
                    for i in range(0, len(group), batch_size):
                        batches.append(list(group[i : i + batch_size]))
                    continue
                current_batch = list(group)
                continue
            if len(current_batch) + len(group) <= batch_size:
                current_batch.extend(group)
            else:
                batches.append(current_batch)
                if len(group) > batch_size:
                    for i in range(0, len(group), batch_size):
                        batches.append(list(group[i : i + batch_size]))
                    current_batch = []
                else:
                    current_batch = list(group)
        if current_batch:
            batches.append(current_batch)

        done = 0
        done_lock = asyncio.Lock()
        progress_lock = asyncio.Lock()

        async def _maybe_report() -> None:
            nonlocal done
            if not progress_reporter or total <= 0:
                return
            async with progress_lock:
                pct = int(min(done, total) / total * 100)
                msg = f"翻译中 {min(done, total)}/{total} 段"
                if isinstance(progress_reporter, MetricsProgressReporter):
                    elapsed = max(0.001, time.monotonic() - started_at)
                    state = await tracker.snapshot(service)
                    async with tokens_lock:
                        prompt_t = int(llm_prompt_tokens)
                        completion_t = int(llm_completion_tokens)
                        calls_t = int(llm_calls)
                    tokens_total = prompt_t + completion_t
                    await progress_reporter.report_metrics(
                        {
                            "progress": pct,
                            "progress_message": msg,
                            "items_processed": int(min(done, total)),
                            "items_total": int(total),
                            "items_per_second": float(min(done, total)) / elapsed,
                            "llm_prompt_tokens": prompt_t,
                            "llm_completion_tokens": completion_t,
                            "llm_calls_count": calls_t,
                            "llm_tokens_per_second": float(tokens_total) / elapsed,
                            "active_tasks": int(state.active),
                            "max_concurrent": int(state.max),
                        }
                    )
                else:
                    await progress_reporter.report(pct, msg)

        async def _translate_batch(batch: list[ASRSegment]) -> dict[int, str]:
            nonlocal done, llm_prompt_tokens, llm_completion_tokens, llm_calls
            batch_items: list[tuple[int, str]] = []
            expected_ids: list[int] = []
            for seg in batch:
                seg_id = int(seg.id)
                expected_ids.append(seg_id)
                batch_items.append((seg_id, _src_text(seg)))

            user_input = self._build_batch_user_input(
                target_language=target_language,
                global_context=global_ctx,
                items=batch_items,
            )

            async with tracker.acquire(service):
                result = await self.llm.complete_with_usage(
                    [
                        Message(role="system", content=system_prompt),
                        Message(role="user", content=user_input),
                    ],
                    temperature=0.2,
                )

            raw_out = getattr(result, "text", "") or ""
            try:
                mapping = self._parse_batch_translation(str(raw_out), expected_ids=expected_ids)
            except ValueError as exc:
                raise StageExecutionError(
                    self.name,
                    f"Failed to parse batch translation output (ids={expected_ids}): {exc}",
                ) from exc

            usage = getattr(result, "usage", None)
            prompt = getattr(usage, "prompt_tokens", None)
            completion = getattr(usage, "completion_tokens", None)
            async with tokens_lock:
                if isinstance(prompt, int):
                    llm_prompt_tokens += int(prompt)
                if isinstance(completion, int):
                    llm_completion_tokens += int(completion)
                llm_calls += 1

            async with done_lock:
                done += len(batch)
            await _maybe_report()
            return mapping

        results = await asyncio.gather(*[_translate_batch(batch) for batch in batches])
        translation_by_id: dict[int, str] = {}
        for mapping in results:
            for seg_id, tr in mapping.items():
                if int(seg_id) not in translation_by_id:
                    translation_by_id[int(seg_id)] = str(tr or "").strip()

        for seg in translatable:
            seg_id = int(seg.id)
            src = _src_text(seg)
            translation = str(translation_by_id.get(seg_id, "") or "").strip()
            translations.append(
                SegmentTranslation(segment_id=seg_id, source_text=src, translation=translation)
            )
            chunks.append(
                SemanticChunk(
                    id=seg_id,
                    text=src,
                    translation=translation,
                    asr_segment_ids=[seg_id],
                    translation_chunks=[],
                )
            )

        context["asr_segments"] = asr_segments
        context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
        context["full_transcript"] = " ".join(
            seg.text for seg in asr_segments if (seg.text or "").strip()
        )
        context["segment_translations"] = translations
        context["semantic_chunks"] = chunks
        logger.info("llm_semantic_chunking done (segment_translations=%d)", len(translations))
        return context
