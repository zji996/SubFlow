"""LLM passes with token limits and greedy semantic chunking."""

from __future__ import annotations

import asyncio
import logging
import json
import time
from typing import Any, cast

from subflow.exceptions import StageExecutionError
from subflow.models.segment import ASRSegment, SemanticChunk, TranslationChunk, VADSegment
from subflow.pipeline.concurrency import ServiceType, get_concurrency_tracker
from subflow.pipeline.context import MetricsProgressReporter, PipelineContext, ProgressReporter
from subflow.providers.llm import Message
from subflow.stages.base_llm import BaseLLMStage
from subflow.utils.tokenizer import truncate_to_tokens, count_tokens
from subflow.utils.translation_distributor import distribute_translation
from subflow.utils.vad_region_mapper import build_region_segment_ids
from subflow.utils.vad_region_partition import partition_vad_regions_by_gap

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

    # Token limits
    MAX_TOTAL_TOKENS = 8000
    MAX_TRANSCRIPT_TOKENS = 6000
    SYSTEM_PROMPT_TOKENS = 500  # Reserved for system prompt

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
        service: ServiceType = "llm_power" if str(self.profile or "").strip().lower() == "power" else "llm_fast"
        tracker = get_concurrency_tracker(self.settings)

        # Fallback if no API key
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

        # Truncate transcript to token limit
        raw_tokens = count_tokens(transcript)
        transcript = truncate_to_tokens(
            transcript,
            self.MAX_TRANSCRIPT_TOKENS,
            strategy="sample",
        )
        logger.info(
            "llm_global_understanding start (tokens=%d->%d, profile=%s)",
            raw_tokens,
            count_tokens(transcript),
            self.profile,
        )

        system_prompt = self._get_system_prompt()

        if progress_reporter is not None:
            if isinstance(progress_reporter, MetricsProgressReporter):
                await progress_reporter.report_metrics({"progress": 0, "progress_message": "全局理解中"})
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
    """Pass 2: Greedy sequential semantic chunking + translation."""

    name = "llm_semantic_chunking"
    profile_attr = "semantic_translation"

    DEFAULT_WINDOW_SIZE = 6
    MAX_WINDOW_SIZE = 15

    def validate_input(self, context: PipelineContext) -> bool:
        return bool(context.get("asr_segments")) and bool(context.get("target_language"))

    def _get_system_prompt(self) -> str:
        # Keep this prompt aligned with docs/llm_multi_pass.md.
        return """你是一位专业的翻译专家。从 ASR 段落中提取第一个语义完整的翻译单元。

## 核心规则

1. **从段落0开始**（除非是纯语气词如 um/uh/嗯/那个 则跳过）
2. **延伸到语义完整为止**，形成一个自然的翻译单元
3. **意译优先**：翻译要通顺自然、信达雅，传达意思而非逐字翻译

## 翻译分段规则

- 你只需要输出完整意译 `translation`
- 程序会将 `translation` 自动均分成每段对应的 `translation_chunks`（无需你输出）

## 输出格式

**情况1：正常输出**
```json
{
  "translation": "完整意译",
  "asr_segment_ids": [0, 1, 2]
}
```

**情况2：窗口不足，需要更多上下文**
```json
{
  "need_more_context": {
    "reason": "当前语义块未完成，句子在段落5处中断",
    "additional_segments": 4
  }
}
```

## 重要约束

- asr_segment_ids 必须覆盖所有被选中的段落（使用当前窗口内的相对 id：0..N-1）
- 如果窗口内所有段落都是语气词/填充词，返回空翻译并覆盖所有段落
- 只在确实无法形成完整语义时才请求更多上下文
"""

    def _get_user_input(
        self,
        *,
        target_language: str,
        input_context: dict[str, Any],
        asr_payload: list[dict[str, Any]],
        previous_chunk: SemanticChunk | None = None,
    ) -> str:
        parts = [f"目标语言：{target_language}"]

        if previous_chunk is not None:
            parts.append(f"\n【上一轮翻译】{previous_chunk.translation}")

        compact_context = _compact_global_context(input_context)
        if compact_context:
            parts.append(f"\n全局上下文：\n{json.dumps(compact_context, ensure_ascii=False)}")

        parts.append(f"\nASR 段落：\n{json.dumps(asr_payload, ensure_ascii=False)}")
        return "\n".join(parts)

    @staticmethod
    def _to_absolute_ids(
        ids: list[int],
        *,
        window_start: int,
        window_len: int,
    ) -> list[int]:
        if not ids:
            return []
        window_end = window_start + window_len
        out: list[int] = []
        for raw in ids:
            i = int(raw)
            if 0 <= i < window_len:
                out.append(window_start + i)
                continue
            if window_start <= i < window_end:
                out.append(i)
                continue
        return out

    @staticmethod
    def _parse_need_more_context(result: dict[str, Any]) -> tuple[int, str] | None:
        raw = result.get("need_more_context")
        if not isinstance(raw, dict):
            return None
        reason = str(raw.get("reason") or "").strip()
        try:
            additional = int(raw.get("additional_segments") or 0)
        except (TypeError, ValueError):
            additional = 0
        return additional, reason

    def _parse_result(
        self,
        result: dict[str, Any],
        *,
        window_start: int,
        window_segments: list[ASRSegment],
        chunk_id: int,
    ) -> tuple[SemanticChunk | None, int]:
        window_len = len(window_segments)
        window_by_abs_id = {window_start + i: seg for i, seg in enumerate(window_segments)}

        translation_chunks: list[TranslationChunk] = []
        covered_ids: set[int] = set()

        raw_chunks = result.get("translation_chunks")
        if isinstance(raw_chunks, list):
            for ch in raw_chunks:
                if not isinstance(ch, dict):
                    continue
                chunk_text = str(ch.get("text") or "").strip()
                raw_segment_id = ch.get("segment_id")
                if raw_segment_id is not None:
                    abs_ids = self._to_absolute_ids(
                        [int(raw_segment_id)],
                        window_start=window_start,
                        window_len=window_len,
                    )
                    if not abs_ids:
                        continue
                    abs_id = int(abs_ids[0])
                    covered_ids.add(abs_id)
                    translation_chunks.append(TranslationChunk(text=chunk_text, segment_id=abs_id))
                    continue

                raw_ids = ch.get("segment_ids")
                if not isinstance(raw_ids, list):
                    raw_ids = []
                abs_ids = self._to_absolute_ids(
                    [int(x) for x in list(raw_ids or [])],
                    window_start=window_start,
                    window_len=window_len,
                )
                seen: set[int] = set()
                for abs_id in abs_ids:
                    abs_id = int(abs_id)
                    if abs_id in seen:
                        continue
                    seen.add(abs_id)
                    covered_ids.add(abs_id)
                    translation_chunks.append(TranslationChunk(text=chunk_text, segment_id=abs_id))

        # Backward compatibility: legacy format with per-segment translations.
        if not translation_chunks:
            raw_segments = result.get("segments")
            if isinstance(raw_segments, list):
                for seg_entry in raw_segments:
                    if not isinstance(seg_entry, dict):
                        continue
                    raw_id = seg_entry.get("id")
                    if raw_id is None:
                        continue
                    seg_id = int(raw_id)
                    seg_translation = str(seg_entry.get("translation", "")).strip()
                    abs_ids = self._to_absolute_ids(
                        [seg_id],
                        window_start=window_start,
                        window_len=window_len,
                    )
                    if not abs_ids:
                        continue
                    abs_id = int(abs_ids[0])
                    covered_ids.add(abs_id)
                    translation_chunks.append(
                        TranslationChunk(text=seg_translation, segment_id=abs_id)
                    )

        asr_segment_ids: list[int] = sorted(covered_ids)

        # Fallback: support legacy format with asr_segment_ids
        if not asr_segment_ids:
            raw_ids = result.get("asr_segment_ids", [])
            # Also support nested chunk format for backward compatibility
            raw_chunk = result.get("chunk")
            if isinstance(raw_chunk, dict):
                raw_ids = raw_chunk.get(
                    "asr_segment_ids", raw_chunk.get("source_segment_ids", raw_ids)
                )

            asr_segment_ids = self._to_absolute_ids(
                [int(x) for x in list(raw_ids or [])],
                window_start=window_start,
                window_len=window_len,
            )

        # Get translation from top level or nested chunk
        translation = str(result.get("translation", "")).strip()
        raw_chunk = result.get("chunk")
        if not translation and isinstance(raw_chunk, dict):
            translation = str(raw_chunk.get("translation", "")).strip()

        chunk: SemanticChunk | None = None
        if asr_segment_ids:
            text_parts: list[str] = []
            covered_segments: list[ASRSegment] = []
            normalized_ids: list[int] = []
            for seg_id in list(asr_segment_ids or []):
                seg = window_by_abs_id.get(seg_id)
                if seg is not None:
                    covered_segments.append(seg)
                    normalized_ids.append(int(seg.id))
                    text_parts.append(str(seg.text or "").strip())
            text = " ".join(text_parts)

            asr_segment_ids = normalized_ids

            # Fallback: if caller only gave a full translation, distribute it programmatically.
            if not translation_chunks and translation and covered_segments:
                translation_chunks = distribute_translation(translation, covered_segments)

            chunk = SemanticChunk(
                id=chunk_id,
                text=text,
                translation=translation,
                asr_segment_ids=asr_segment_ids,
                translation_chunks=translation_chunks,
            )

        # Auto-calculate next_cursor from chunk.asr_segment_ids
        if chunk is not None and chunk.asr_segment_ids:
            next_cursor = max(chunk.asr_segment_ids) + 1
        else:
            # No chunk, force advance by window size to avoid infinite loop
            next_cursor = window_start + len(window_segments)

        return chunk, next_cursor

    async def execute(
        self,
        context: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> PipelineContext:
        context = cast(PipelineContext, dict(context))
        asr_segments: list[ASRSegment] = list(context.get("asr_segments", []))
        target_language = str(context.get("target_language", "zh"))
        parallel_enabled = bool(getattr(self.settings, "parallel", None) and self.settings.parallel.enabled)
        vad_regions: list[VADSegment] = list(context.get("vad_regions") or [])
        started_at = time.monotonic()
        llm_prompt_tokens = 0
        llm_completion_tokens = 0
        llm_calls = 0
        tokens_lock = asyncio.Lock()
        service: ServiceType = "llm_power" if str(self.profile or "").strip().lower() == "power" else "llm_fast"
        tracker = get_concurrency_tracker(self.settings)

        # Fallback if no API key
        if not self.api_key:
            logger.info("llm_semantic_chunking fallback (no api key, profile=%s)", self.profile)
            context["semantic_chunks"] = [
                SemanticChunk(
                    id=segment.id,
                    text=segment.text,
                    translation=f"[{target_language}] {segment.text}",
                    asr_segment_ids=[segment.id],
                    translation_chunks=[
                        TranslationChunk(
                            text=f"[{target_language}] {segment.text}",
                            segment_id=segment.id,
                        )
                    ],
                )
                for segment in asr_segments
                if (segment.text or "").strip()
            ]
            context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
            return context

        llm_limit = max(1, int(self.get_concurrency_limit(self.settings)))
        llm_semaphore = asyncio.Semaphore(llm_limit)

        async def _complete_json(messages: list[Message]) -> Any:
            nonlocal llm_prompt_tokens, llm_completion_tokens, llm_calls
            async with llm_semaphore:
                async with tracker.acquire(service):
                    helper = self.json_helper
                    complete_with_usage = getattr(helper, "complete_json_with_usage", None)
                    if callable(complete_with_usage):
                        result, usage = await complete_with_usage(messages)
                    else:
                        result = await helper.complete_json(messages)
                        usage = None

            if usage is not None:
                prompt = getattr(usage, "prompt_tokens", None)
                completion = getattr(usage, "completion_tokens", None)
                async with tokens_lock:
                    if isinstance(prompt, int):
                        llm_prompt_tokens += int(prompt)
                    if isinstance(completion, int):
                        llm_completion_tokens += int(completion)
                    llm_calls += 1
            return result

        async def _run_partition(
            partition_segments: list[ASRSegment],
        ) -> list[SemanticChunk]:
            if not partition_segments:
                return []

            base_id = int(partition_segments[0].id)
            id_list = [int(s.id) for s in partition_segments]
            index_by_id: dict[int, int] = {sid: i for i, sid in enumerate(id_list)}

            def _abs_to_local(abs_cursor: int) -> int:
                if abs_cursor in index_by_id:
                    return int(index_by_id[abs_cursor])
                rel = int(abs_cursor) - base_id
                if 0 <= rel <= len(partition_segments):
                    return rel
                # Fallback: resume from first segment whose id >= abs_cursor.
                for i, seg in enumerate(partition_segments):
                    if int(seg.id) >= int(abs_cursor):
                        return i
                return len(partition_segments)

            local_chunks: list[SemanticChunk] = []
            local_cursor = 0
            chunk_id = 0
            window_size = self.DEFAULT_WINDOW_SIZE
            input_context = _compact_global_context(context.get("global_context"))

            while local_cursor < len(partition_segments):
                prev_cursor = local_cursor
                window_end = min(local_cursor + window_size, len(partition_segments))
                window = partition_segments[local_cursor:window_end]
                if not window:
                    break

                window_start_abs = int(window[0].id)

                asr_payload = [
                    {"id": i, "start": s.start, "end": s.end, "text": s.text}
                    for i, s in enumerate(window)
                ]

                system_prompt = self._get_system_prompt()
                previous_chunk = local_chunks[-1] if local_chunks else None
                user_input = self._get_user_input(
                    target_language=target_language,
                    input_context=input_context,
                    asr_payload=asr_payload,
                    previous_chunk=previous_chunk,
                )

                result = await _complete_json(
                    [
                        Message(role="system", content=system_prompt),
                        Message(role="user", content=user_input),
                    ]
                )
                if not isinstance(result, dict):
                    raise StageExecutionError(self.name, "Semantic chunking output must be a JSON object")

                need_more = self._parse_need_more_context(result)
                if need_more is not None:
                    additional, reason = need_more
                    if additional > 0:
                        new_size = min(window_size + additional, self.MAX_WINDOW_SIZE)
                        if new_size > window_size:
                            logger.info(
                                "llm_semantic_chunking expand window (cursor=%d, size=%d->%d, reason=%s)",
                                window_start_abs,
                                window_size,
                                new_size,
                                reason,
                            )
                            window_size = new_size
                            continue

                    if window_size >= self.MAX_WINDOW_SIZE:
                        forced_note = "已达到最大窗口限制，请不要返回 need_more_context，必须输出情况1 的 JSON。"
                    else:
                        forced_note = "additional_segments 必须为正数；请不要返回 need_more_context，必须输出情况1 的 JSON。"
                    forced_prompt = system_prompt + f"\n\n【系统提示】{forced_note}"
                    logger.warning(
                        "llm_semantic_chunking force output (cursor=%d, window_size=%d, reason=%s, additional=%d)",
                        window_start_abs,
                        window_size,
                        reason,
                        additional,
                    )
                    forced = await _complete_json(
                        [
                            Message(role="system", content=forced_prompt),
                            Message(role="user", content=user_input),
                        ]
                    )
                    if not isinstance(forced, dict):
                        raise StageExecutionError(self.name, "Semantic chunking output must be a JSON object")
                    result = forced

                    still_need_more = self._parse_need_more_context(result)
                    has_any_translation = any(
                        key in result
                        for key in ("translation", "translation_chunks", "segments", "asr_segment_ids", "chunk")
                    )
                    if still_need_more is not None and not has_any_translation:
                        raise StageExecutionError(
                            self.name,
                            "LLM requested more context at max window without providing translation output",
                        )

                new_chunk, next_cursor_abs = self._parse_result(
                    result,
                    window_start=window_start_abs,
                    window_segments=window,
                    chunk_id=chunk_id,
                )

                if new_chunk is None:
                    local_cursor = _abs_to_local(next_cursor_abs) if next_cursor_abs > window_start_abs else local_cursor + 1
                    window_size = self.DEFAULT_WINDOW_SIZE
                else:
                    local_chunks.append(new_chunk)
                    chunk_id += 1
                    local_cursor = _abs_to_local(next_cursor_abs)
                    window_size = self.DEFAULT_WINDOW_SIZE

                if local_cursor <= prev_cursor:
                    local_cursor = prev_cursor + 1

            return local_chunks

        if parallel_enabled and len(vad_regions) > 1:
            partitions = partition_vad_regions_by_gap(
                vad_regions,
                min_gap_seconds=float(self.settings.parallel.min_gap_seconds),
            )
            logger.info(
                "llm_semantic_chunking region partitions (regions=%d, partitions=%d, min_gap=%.2fs, concurrency=%d)",
                len(vad_regions),
                len(partitions),
                float(self.settings.parallel.min_gap_seconds),
                llm_limit,
            )

            segment_regions = [VADSegment(start=s.start, end=s.end) for s in asr_segments]
            region_segment_ids = build_region_segment_ids(vad_regions, segment_regions)
            if not region_segment_ids and asr_segments:
                region_segment_ids = [list(range(len(asr_segments)))]

            partition_segments_list: list[list[ASRSegment]] = []
            for part in partitions:
                seg_ids: list[int] = []
                for rid in part.region_ids():
                    if 0 <= int(rid) < len(region_segment_ids):
                        seg_ids.extend(region_segment_ids[int(rid)])
                if not seg_ids:
                    continue
                partition_segments_list.append([asr_segments[i] for i in seg_ids])

            total_segments = len(asr_segments)
            if progress_reporter and total_segments > 0:
                if isinstance(progress_reporter, MetricsProgressReporter):
                    state = await tracker.snapshot(service)
                    await progress_reporter.report_metrics(
                        {
                            "progress": 0,
                            "progress_message": f"翻译中 0/{total_segments} 段",
                            "items_processed": 0,
                            "items_total": int(total_segments),
                            "items_per_second": 0.0,
                            "active_tasks": int(state.active),
                            "max_concurrent": int(state.max),
                        }
                    )
                else:
                    await progress_reporter.report(0, f"翻译中 0/{total_segments} 段")

            done_segments = 0
            done_lock = asyncio.Lock()

            async def _wrap(part_segs: list[ASRSegment]) -> list[SemanticChunk]:
                nonlocal done_segments
                chunks = await _run_partition(part_segs)
                async with done_lock:
                    done_segments += len(part_segs)
                    if progress_reporter and total_segments > 0:
                        pct = int(min(done_segments, total_segments) / total_segments * 100)
                        processed = int(min(done_segments, total_segments))
                        msg = f"翻译中 {processed}/{total_segments} 段"
                        if isinstance(progress_reporter, MetricsProgressReporter):
                            elapsed = max(0.001, time.monotonic() - started_at)
                            state = await tracker.snapshot(service)
                            async with tokens_lock:
                                prompt = int(llm_prompt_tokens)
                                completion = int(llm_completion_tokens)
                                calls = int(llm_calls)
                            tokens_total = prompt + completion
                            await progress_reporter.report_metrics(
                                {
                                    "progress": pct,
                                    "progress_message": msg,
                                    "items_processed": processed,
                                    "items_total": int(total_segments),
                                    "items_per_second": float(processed) / elapsed,
                                    "llm_prompt_tokens": prompt,
                                    "llm_completion_tokens": completion,
                                    "llm_calls_count": calls,
                                    "llm_tokens_per_second": float(tokens_total) / elapsed,
                                    "active_tasks": int(state.active),
                                    "max_concurrent": int(state.max),
                                }
                            )
                        else:
                            await progress_reporter.report(pct, msg)
                return chunks

            partition_results = await asyncio.gather(*[_wrap(segs) for segs in partition_segments_list])
            all_chunks = [c for chunks in partition_results for c in chunks]

            asr_by_id: dict[int, ASRSegment] = {int(s.id): s for s in asr_segments}

            def _chunk_sort_key(ch: SemanticChunk) -> tuple[float, int]:
                for sid in list(ch.asr_segment_ids or []):
                    seg = asr_by_id.get(int(sid))
                    if seg is not None:
                        return (float(seg.start), int(sid))
                return (float("inf"), int(ch.id))

            all_chunks.sort(key=_chunk_sort_key)
            for i, ch in enumerate(all_chunks):
                ch.id = i

            context["asr_segments"] = asr_segments
            context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
            context["full_transcript"] = " ".join(seg.text for seg in asr_segments if seg.text)
            context["semantic_chunks"] = all_chunks
            logger.info("llm_semantic_chunking done (chunks=%d)", len(all_chunks))
            return context

        # Greedy sequential processing (legacy behavior)
        logger.info("llm_semantic_chunking start (asr_segments=%d)", len(asr_segments))
        all_chunks: list[SemanticChunk] = []
        cursor = 0
        chunk_id = 0
        window_size = self.DEFAULT_WINDOW_SIZE
        input_context = _compact_global_context(context.get("global_context"))
        total_segments = len(asr_segments)

        while cursor < len(asr_segments):
            prev_cursor = cursor
            # Get window
            window_end = min(cursor + window_size, len(asr_segments))
            window = asr_segments[cursor:window_end]

            if not window:
                break

            # Build payload with relative IDs for this window
            asr_payload = [
                {"id": i, "start": s.start, "end": s.end, "text": s.text}
                for i, s in enumerate(window)
            ]

            # Call LLM
            system_prompt = self._get_system_prompt()
            # Get previous chunk for context (if any)
            previous_chunk = all_chunks[-1] if all_chunks else None

            user_input = self._get_user_input(
                target_language=target_language,
                input_context=input_context,
                asr_payload=asr_payload,
                previous_chunk=previous_chunk,
            )

            result = await _complete_json(
                [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user_input),
                ]
            )

            if not isinstance(result, dict):
                raise StageExecutionError(
                    self.name, "Semantic chunking output must be a JSON object"
                )

            need_more = self._parse_need_more_context(result)
            if need_more is not None:
                additional, reason = need_more
                if additional > 0:
                    new_size = min(window_size + additional, self.MAX_WINDOW_SIZE)
                    if new_size > window_size:
                        logger.info(
                            "llm_semantic_chunking expand window (cursor=%d, size=%d->%d, reason=%s)",
                            cursor,
                            window_size,
                            new_size,
                            reason,
                        )
                        window_size = new_size
                        continue

                # Cannot expand further (max reached or invalid request): retry once and force output.
                if window_size >= self.MAX_WINDOW_SIZE:
                    forced_note = "已达到最大窗口限制，请不要返回 need_more_context，必须输出情况1 的 JSON。"
                else:
                    forced_note = "additional_segments 必须为正数；请不要返回 need_more_context，必须输出情况1 的 JSON。"
                forced_prompt = system_prompt + f"\n\n【系统提示】{forced_note}"
                logger.warning(
                    "llm_semantic_chunking force output (cursor=%d, window_size=%d, reason=%s, additional=%d)",
                    cursor,
                    window_size,
                    reason,
                    additional,
                )
                forced = await _complete_json(
                    [
                        Message(role="system", content=forced_prompt),
                        Message(role="user", content=user_input),
                    ]
                )
                if not isinstance(forced, dict):
                    raise StageExecutionError(
                        self.name, "Semantic chunking output must be a JSON object"
                    )
                result = forced

                still_need_more = self._parse_need_more_context(result)
                has_any_translation = any(
                    key in result
                    for key in ("translation", "translation_chunks", "segments", "asr_segment_ids", "chunk")
                )
                if still_need_more is not None and not has_any_translation:
                    raise StageExecutionError(
                        self.name,
                        "LLM requested more context at max window without providing translation output",
                    )

            new_chunk, next_cursor = self._parse_result(
                result,
                window_start=cursor,
                window_segments=window,
                chunk_id=chunk_id,
            )

            if new_chunk is None:
                # No chunks extracted (all fillers?), force advance
                cursor = next_cursor if next_cursor > cursor else cursor + 1
                window_size = self.DEFAULT_WINDOW_SIZE
            else:
                all_chunks.append(new_chunk)
                chunk_id += 1
                cursor = next_cursor
                window_size = self.DEFAULT_WINDOW_SIZE

            # Safety: prevent infinite loop
            if cursor <= prev_cursor:
                cursor = prev_cursor + 1

            if progress_reporter and total_segments > 0:
                processed = min(cursor, total_segments)
                pct = int(processed / total_segments * 100)
                msg = f"翻译中 {processed}/{total_segments} 段"
                if isinstance(progress_reporter, MetricsProgressReporter):
                    elapsed = max(0.001, time.monotonic() - started_at)
                    state = await tracker.snapshot(service)
                    async with tokens_lock:
                        prompt = int(llm_prompt_tokens)
                        completion = int(llm_completion_tokens)
                        calls = int(llm_calls)
                    tokens_total = prompt + completion
                    await progress_reporter.report_metrics(
                        {
                            "progress": pct,
                            "progress_message": msg,
                            "items_processed": int(processed),
                            "items_total": int(total_segments),
                            "items_per_second": float(processed) / elapsed,
                            "llm_prompt_tokens": prompt,
                            "llm_completion_tokens": completion,
                            "llm_calls_count": calls,
                            "llm_tokens_per_second": float(tokens_total) / elapsed,
                            "active_tasks": int(state.active),
                            "max_concurrent": int(state.max),
                        }
                    )
                else:
                    await progress_reporter.report(pct, msg)

        context["asr_segments"] = asr_segments
        context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
        context["full_transcript"] = " ".join(seg.text for seg in asr_segments if seg.text)
        context["semantic_chunks"] = all_chunks
        logger.info(
            "llm_semantic_chunking done (chunks=%d)",
            len(all_chunks),
        )
        return context
