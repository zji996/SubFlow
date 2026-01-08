"""LLM passes with token limits and greedy semantic chunking."""

from __future__ import annotations

import logging
import json
from typing import Any, cast

from subflow.exceptions import StageExecutionError
from subflow.models.segment import ASRSegment, SemanticChunk, TranslationChunk
from subflow.pipeline.context import PipelineContext
from subflow.providers.llm import Message
from subflow.stages.base_llm import BaseLLMStage
from subflow.utils.tokenizer import truncate_to_tokens, count_tokens

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

    async def execute(self, context: PipelineContext) -> PipelineContext:
        context = cast(PipelineContext, dict(context))
        transcript = str(context.get("full_transcript", "")).strip()

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

        result = await self.json_helper.complete_json(
            [
                Message(role="system", content=system_prompt),
                Message(role="user", content=transcript),
            ]
        )
        if not isinstance(result, dict):
            raise StageExecutionError(
                self.name, "Global understanding output must be a JSON object"
            )
        context["global_context"] = cast(dict[str, Any], result)
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

## 翻译分段规则 (translation_chunks)

- 每个 chunk 是翻译的一个语义片段，映射到一个或多个 segment_ids
- 分段方式由目标语言的语序和语义决定，不必与原文段落一一对应
- 所有 chunks 拼接后 = 完整翻译 (translation)
- 所有 segment_ids 合并后 = 覆盖的段落范围

## 输出格式

**情况1：正常输出**
```json
{
  "translation": "完整意译",
  "translation_chunks": [
    {"text": "翻译片段1", "segment_ids": [0, 1]},
    {"text": "翻译片段2", "segment_ids": [2]}
  ]
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

- translation_chunks 的 segment_ids 合并后必须覆盖所有被选中的段落
- 如果窗口内所有段落都是语气词/填充词，返回空翻译并覆盖所有段落
- 只在确实无法形成完整语义时才请求更多上下文
"""

    def _get_user_input(
        self,
        *,
        target_language: str,
        input_context: dict[str, Any],
        asr_payload: list[dict],
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
                raw_ids = ch.get("segment_ids")
                if not isinstance(raw_ids, list):
                    raw_ids = []
                abs_ids = self._to_absolute_ids(
                    [int(x) for x in list(raw_ids or [])],
                    window_start=window_start,
                    window_len=window_len,
                )
                abs_ids = sorted(set(abs_ids))
                if not abs_ids:
                    continue
                covered_ids.update(abs_ids)
                translation_chunks.append(
                    TranslationChunk(text=chunk_text, segment_ids=abs_ids)
                )

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
                        TranslationChunk(text=seg_translation, segment_ids=[abs_id])
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
            for seg_id in asr_segment_ids:
                seg = window_by_abs_id.get(seg_id)
                if seg is not None:
                    text_parts.append(str(seg.text or "").strip())
            text = " ".join(text_parts)

            # Fallback: if caller only gave a full translation, treat it as a single chunk.
            if not translation_chunks and translation:
                translation_chunks = [
                    TranslationChunk(text=translation, segment_ids=list(asr_segment_ids))
                ]

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

    async def execute(self, context: PipelineContext) -> PipelineContext:
        context = cast(PipelineContext, dict(context))
        asr_segments: list[ASRSegment] = list(context.get("asr_segments", []))
        target_language = str(context.get("target_language", "zh"))

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
                            segment_ids=[segment.id],
                        )
                    ],
                )
                for segment in asr_segments
                if (segment.text or "").strip()
            ]
            context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
            return context

        # Greedy sequential processing
        logger.info("llm_semantic_chunking start (asr_segments=%d)", len(asr_segments))
        all_chunks: list[SemanticChunk] = []
        cursor = 0
        chunk_id = 0
        window_size = self.DEFAULT_WINDOW_SIZE
        input_context = _compact_global_context(context.get("global_context"))

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

            result = await self.json_helper.complete_json(
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
                forced = await self.json_helper.complete_json(
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

        context["asr_segments"] = asr_segments
        context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
        context["full_transcript"] = " ".join(seg.text for seg in asr_segments if seg.text)
        context["semantic_chunks"] = all_chunks
        logger.info(
            "llm_semantic_chunking done (chunks=%d)",
            len(all_chunks),
        )
        return context
