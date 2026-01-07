"""LLM passes with token limits and greedy semantic chunking."""

from __future__ import annotations

import logging
import json
from typing import Any, cast

from subflow.config import Settings
from subflow.exceptions import StageExecutionError
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk
from subflow.pipeline.context import PipelineContext
from subflow.providers import get_llm_provider
from subflow.providers.llm import Message
from subflow.stages.base import Stage
from subflow.utils.llm_json import LLMJSONHelper
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


class GlobalUnderstandingPass(Stage):
    """Pass 1: Global understanding with 8000 token limit."""
    
    name = "llm_global_understanding"
    
    # Token limits
    MAX_TOTAL_TOKENS = 8000
    MAX_TRANSCRIPT_TOKENS = 6000
    SYSTEM_PROMPT_TOKENS = 500  # Reserved for system prompt
    
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm = get_llm_provider(settings.llm.model_dump())
        self.json_helper = LLMJSONHelper(self.llm, max_retries=3)

    async def close(self) -> None:
        await self.llm.close()

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
        if not self.settings.llm.api_key:
            logger.info("llm_global_understanding fallback (no api key)")
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
            "llm_global_understanding start (tokens=%d->%d)",
            raw_tokens,
            count_tokens(transcript),
        )

        system_prompt = self._get_system_prompt()
        
        result = await self.json_helper.complete_json(
            [
                Message(role="system", content=system_prompt),
                Message(role="user", content=transcript),
            ]
        )
        if not isinstance(result, dict):
            raise StageExecutionError(self.name, "Global understanding output must be a JSON object")
        context["global_context"] = cast(dict[str, Any], result)
        logger.info("llm_global_understanding done")
        return context


class SemanticChunkingPass(Stage):
    """Pass 2: Greedy sequential semantic chunking + correction + translation."""
    
    name = "llm_semantic_chunking"
    
    # Greedy algorithm settings
    WINDOW_SIZE = 6  # ASR segments to consider at once
    CHUNKS_PER_REQUEST = 1  # Extract the first meaningful chunk each request

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm = get_llm_provider(settings.llm.model_dump())
        self.json_helper = LLMJSONHelper(self.llm, max_retries=3)

    async def close(self) -> None:
        await self.llm.close()

    def validate_input(self, context: PipelineContext) -> bool:
        return bool(context.get("asr_segments")) and bool(context.get("target_language"))

    def _get_system_prompt(self) -> str:
        return (
            "从 ASR 段落提取第一个语义完整的翻译单元。\n\n"
            "规则：\n"
            "1. 必须从段落0开始（除非是纯语气词如um/uh则跳过）\n"
            "2. 延伸到语义完整为止\n"
            "3. 意译：翻译要通顺自然，传达意思而非逐字翻译\n"
            "4. 删除幻觉（如 transcribe the speech）\n\n"
            "只输出 JSON：\n"
            "```json\n"
            "{\n"
            '  "translation": "意译结果",\n'
            '  "asr_segment_ids": [0, 1, 2]\n'
            "}\n"
            "```"
        )

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


    def _parse_result(
        self,
        result: dict[str, Any],
        *,
        window_start: int,
        window_segments: list[ASRSegment],
        chunk_id: int,
    ) -> tuple[dict[int, ASRCorrectedSegment], SemanticChunk | None, int]:
        window_len = len(window_segments)
        window_by_abs_id = {window_start + i: seg for i, seg in enumerate(window_segments)}

        corrected_map: dict[int, ASRCorrectedSegment] = {}
        for item in list(result.get("corrected_segments", []) or []):
            if not isinstance(item, dict):
                continue
            raw_id = item.get("asr_segment_id")
            if raw_id is None:
                continue
            abs_ids = self._to_absolute_ids(
                [int(raw_id)], window_start=window_start, window_len=window_len
            )
            if not abs_ids:
                continue
            abs_id = abs_ids[0]

            corrected_text = str(item.get("text", "")).strip()
            if not corrected_text:
                corrected_text = str(getattr(window_by_abs_id.get(abs_id), "text", "") or "").strip()

            corrected_map[abs_id] = ASRCorrectedSegment(
                id=abs_id,
                asr_segment_id=abs_id,
                text=corrected_text,
            )

        # Parse chunk from top-level fields (simplified format)
        raw_ids = result.get("asr_segment_ids", [])
        # Also support nested chunk format for backward compatibility
        raw_chunk = result.get("chunk")
        if isinstance(raw_chunk, dict):
            raw_ids = raw_chunk.get("asr_segment_ids", raw_chunk.get("source_segment_ids", raw_ids))
        
        asr_segment_ids = self._to_absolute_ids(
            [int(x) for x in list(raw_ids or [])],
            window_start=window_start,
            window_len=window_len,
        )
        
        # Get translation from top level or nested chunk
        translation = str(result.get("translation", "")).strip()
        if not translation and isinstance(raw_chunk, dict):
            translation = str(raw_chunk.get("translation", "")).strip()
        
        chunk: SemanticChunk | None = None
        if asr_segment_ids and translation:
            # Build text from corrected segments or original
            text_parts = []
            for seg_id in asr_segment_ids:
                if seg_id in corrected_map:
                    text_parts.append(corrected_map[seg_id].text)
                elif seg_id in window_by_abs_id:
                    text_parts.append(window_by_abs_id[seg_id].text)
            text = " ".join(text_parts)
            
            chunk = SemanticChunk(
                id=chunk_id,
                text=text,
                translation=translation,
                asr_segment_ids=asr_segment_ids,
            )

        # Auto-calculate next_cursor from chunk.asr_segment_ids
        if chunk is not None and chunk.asr_segment_ids:
            next_cursor = max(chunk.asr_segment_ids) + 1
        else:
            # No chunk, force advance by window size to avoid infinite loop
            next_cursor = window_start + len(window_segments)

        return corrected_map, chunk, next_cursor

    async def execute(self, context: PipelineContext) -> PipelineContext:
        context = cast(PipelineContext, dict(context))
        asr_segments: list[ASRSegment] = list(context.get("asr_segments", []))
        target_language = str(context.get("target_language", "zh"))
        
        # Fallback if no API key
        if not self.settings.llm.api_key:
            logger.info("llm_semantic_chunking fallback (no api key)")
            context["semantic_chunks"] = [
                SemanticChunk(
                    id=segment.id,
                    text=segment.text,
                    translation=f"[{target_language}] {segment.text}",
                    asr_segment_ids=[segment.id],
                )
                for segment in asr_segments
                if (segment.text or "").strip()
            ]
            context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
            context["asr_corrected_segments"] = {
                seg.id: ASRCorrectedSegment(
                    id=seg.id,
                    asr_segment_id=seg.id,
                    text=seg.text,
                )
                for seg in asr_segments
            }
            return context

        # Greedy sequential processing
        logger.info("llm_semantic_chunking start (asr_segments=%d)", len(asr_segments))
        all_chunks: list[SemanticChunk] = []
        cursor = 0
        chunk_id = 0
        input_context = _compact_global_context(context.get("global_context"))
        corrected_segments: dict[int, ASRCorrectedSegment] = dict(
            context.get("asr_corrected_segments", {}) or {}
        )
        
        while cursor < len(asr_segments):
            prev_cursor = cursor
            # Get window
            window_end = min(cursor + self.WINDOW_SIZE, len(asr_segments))
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
                raise StageExecutionError(self.name, "Semantic chunking output must be a JSON object")

            new_corrected, new_chunk, next_cursor = self._parse_result(
                result,
                window_start=cursor,
                window_segments=window,
                chunk_id=chunk_id,
            )

            corrected_segments.update(new_corrected)

            # Apply corrected segment text back to ASR segments
            for seg_id, corrected in new_corrected.items():
                if 0 <= seg_id < len(asr_segments) and corrected.text:
                    asr_segments[seg_id].text = corrected.text
            
            if new_chunk is None:
                # No chunks extracted (all fillers?), force advance
                cursor = next_cursor if next_cursor > cursor else cursor + 1
            else:
                all_chunks.append(new_chunk)
                chunk_id += 1
                cursor = next_cursor
            
            # Safety: prevent infinite loop
            if cursor <= prev_cursor:
                cursor = prev_cursor + 1
        
        # Build corrected segment table (ensure every segment has a record)
        for seg in asr_segments:
            existing = corrected_segments.get(seg.id)
            if existing is None:
                corrected_segments[seg.id] = ASRCorrectedSegment(
                    id=seg.id,
                    asr_segment_id=seg.id,
                    text=seg.text,
                )
            elif not existing.text:
                existing.text = seg.text

        context["asr_segments"] = asr_segments
        context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
        context["asr_corrected_segments"] = corrected_segments
        context["full_transcript"] = " ".join(
            seg.text for seg in asr_segments if seg.text
        )
        context["semantic_chunks"] = all_chunks
        logger.info(
            "llm_semantic_chunking done (chunks=%d)",
            len(all_chunks),
        )
        return context
