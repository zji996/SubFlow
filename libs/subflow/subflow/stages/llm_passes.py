"""LLM passes with token limits and greedy semantic chunking."""

from __future__ import annotations

import logging
import json
from typing import Any

from subflow.config import Settings
from subflow.exceptions import StageExecutionError
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, Correction, SemanticChunk
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
    
    def __init__(self, settings: Settings):
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
        context = dict(context)
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
        context["global_context"] = result
        logger.info("llm_global_understanding done")
        return context


class SemanticChunkingPass(Stage):
    """Pass 2: Greedy sequential semantic chunking + correction + translation."""
    
    name = "llm_semantic_chunking"
    
    # Greedy algorithm settings
    WINDOW_SIZE = 40  # ASR segments to consider at once
    CHUNKS_PER_REQUEST = 1  # Extract the first meaningful chunk each request

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = get_llm_provider(settings.llm.model_dump())
        self.json_helper = LLMJSONHelper(self.llm, max_retries=3)

    async def close(self) -> None:
        await self.llm.close()

    def validate_input(self, context: PipelineContext) -> bool:
        return bool(context.get("asr_segments")) and bool(context.get("target_language"))

    def _get_system_prompt(self) -> str:
        return (
            "你是一个专业的字幕切分、纠错与翻译助手。\n\n"
            "任务：从给定窗口的 ASR 段落中，提取“第一个”语义完整、翻译友好的语义块（字幕翻译单元），并输出其翻译。\n\n"
            "处理规则：\n"
            '1) 跳过前置语气词：如“嗯”“那个”“就是”“然后”等无实际意义的填充词\n'
            "2) ASR 纠错：仅修正谐音字错误；不修正断句错误、重复词、漏字等其他问题\n"
            "3) 语义完整性：每块表达一个完整意思\n"
            "4) 翻译友好：切分点便于目标语言自然表达\n"
            "5) 长度适中：每块原文 10-30 词（翻译后约 15-40 汉字）\n"
            "6) 时间对齐：输出必须保留与原始 ASR 段落的映射关系（asr_segment_ids）\n"
            "7) 翻译：输出 chunk.translation，适合字幕显示；遵循 glossary 与 translation_notes\n\n"
            "输出格式（JSON，仅输出第一个语义块；所有 id 都是窗口内相对序号；用 ```json ... ``` 包裹）：\n"
            "```json\n"
            "{\n"
            '  "filler_segment_ids": [0, 1],\n'
            '  "corrected_segments": [\n'
            "    {\n"
            '      "asr_segment_id": 2,\n'
            '      "corrections": [\n'
            '        {"original": "错误文本", "corrected": "正确文本"}\n'
            "      ]\n"
            "    }\n"
            "  ],\n"
            '  "chunk": {\n'
            '    "text": "纠错后语义块原文",\n'
            '    "translation": "翻译结果（字幕风格）",\n'
            '    "asr_segment_ids": [2, 3]\n'
            "  },\n"
            '  "next_cursor": 4\n'
            "}\n"
            "```\n\n"
            "说明：\n"
            "- `filler_segment_ids`: 被跳过的语气词段落 ID（从当前窗口开头算起）\n"
            "- `corrected_segments`: 被纠错的 ASR 段落；如无纠错可为空数组或直接省略\n"
            "- `chunk.asr_segment_ids`: 构成该语义块的 ASR 段落 ID\n"
            "- `next_cursor`: 下一次应从 segments 中的哪个位置继续（相对于输入数组）\n"
            "- 如果剩余全是语气词，chunk 可为 null，next_cursor 设为最后位置\n"
        )

    def _get_user_input(
        self,
        *,
        target_language: str,
        input_context: dict[str, Any],
        asr_payload: list[dict],
    ) -> str:
        return (
            f"目标语言：{target_language}\n\n"
            "视频全局上下文（用于风格与术语一致性参考）：\n"
            f"```json\n{json.dumps(input_context, ensure_ascii=False, indent=2)}\n```\n\n"
            "窗口内 ASR 段落（id 为窗口内相对序号）：\n"
            f"```json\n{json.dumps(asr_payload, ensure_ascii=False, indent=2)}\n```\n"
        )

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
    def _apply_corrections(original_text: str, corrections: list[Correction]) -> str:
        result = original_text
        for corr in corrections:
            if not corr.original or not corr.corrected:
                continue
            if corr.original == corr.corrected:
                continue
            result = result.replace(corr.original, corr.corrected)
        return result

    def _parse_result(
        self,
        result: dict[str, Any],
        *,
        window_start: int,
        window_segments: list[ASRSegment],
        chunk_id: int,
    ) -> tuple[set[int], dict[int, ASRCorrectedSegment], SemanticChunk | None, int]:
        window_len = len(window_segments)
        window_by_abs_id = {window_start + i: seg for i, seg in enumerate(window_segments)}

        filler_rel = [int(x) for x in list(result.get("filler_segment_ids", []) or [])]
        filler_abs = set(
            self._to_absolute_ids(filler_rel, window_start=window_start, window_len=window_len)
        )

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

            corrections: list[Correction] = []
            for corr in list(item.get("corrections", []) or []):
                if not isinstance(corr, dict):
                    continue
                corrections.append(
                    Correction(
                        original=str(corr.get("original", "")).strip(),
                        corrected=str(corr.get("corrected", "")).strip(),
                    )
                )

            fallback_text = str(item.get("text", "")).strip()
            if fallback_text:
                corrected_text = fallback_text
            else:
                original_text = str(getattr(window_by_abs_id.get(abs_id), "text", "") or "")
                corrected_text = self._apply_corrections(original_text, corrections)

            corrected_map[abs_id] = ASRCorrectedSegment(
                id=abs_id,
                asr_segment_id=abs_id,
                text=corrected_text.strip(),
                corrections=corrections,
                is_filler=False,
            )

        raw_chunk = result.get("chunk")
        chunk: SemanticChunk | None = None
        if isinstance(raw_chunk, dict):
            raw_ids = raw_chunk.get("asr_segment_ids", raw_chunk.get("source_segment_ids", []))
            asr_segment_ids = self._to_absolute_ids(
                [int(x) for x in list(raw_ids or [])],
                window_start=window_start,
                window_len=window_len,
            )
            text = str(raw_chunk.get("text", "")).strip()
            translation = str(raw_chunk.get("translation", "")).strip()
            if text and asr_segment_ids:
                chunk = SemanticChunk(
                    id=chunk_id,
                    text=text,
                    translation=translation or text,
                    asr_segment_ids=asr_segment_ids,
                )

        raw_next = int(result.get("next_cursor", window_len))
        if 0 <= raw_next <= window_len:
            next_cursor = window_start + raw_next
        else:
            next_cursor = raw_next

        return filler_abs, corrected_map, chunk, next_cursor

    async def execute(self, context: PipelineContext) -> PipelineContext:
        context = dict(context)
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
                    corrections=[],
                    is_filler=False,
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
        filler_ids: set[int] = set()
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
            user_input = self._get_user_input(
                target_language=target_language,
                input_context=input_context,
                asr_payload=asr_payload,
            )
            result = await self.json_helper.complete_json(
                [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user_input),
                ]
            )
            
            if not isinstance(result, dict):
                raise StageExecutionError(self.name, "Semantic chunking output must be a JSON object")
            
            new_filler_ids, new_corrected, new_chunk, next_cursor = self._parse_result(
                result,
                window_start=cursor,
                window_segments=window,
                chunk_id=chunk_id,
            )

            filler_ids |= new_filler_ids
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
            is_filler = seg.id in filler_ids
            existing = corrected_segments.get(seg.id)
            if existing is None:
                corrected_segments[seg.id] = ASRCorrectedSegment(
                    id=seg.id,
                    asr_segment_id=seg.id,
                    text=seg.text,
                    corrections=[],
                    is_filler=is_filler,
                )
            else:
                existing.is_filler = is_filler
                if not existing.text:
                    existing.text = seg.text

        context["asr_segments"] = asr_segments
        context["asr_segments_index"] = {seg.id: seg for seg in asr_segments}
        context["asr_corrected_segments"] = corrected_segments
        context["full_transcript"] = " ".join(
            seg.text for seg in asr_segments if seg.text and seg.id not in filler_ids
        )
        context["semantic_chunks"] = all_chunks
        logger.info(
            "llm_semantic_chunking done (chunks=%d, fillers=%d)",
            len(all_chunks),
            len(filler_ids),
        )
        return context
