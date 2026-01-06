"""LLM passes (mock implementation)."""

from __future__ import annotations

from typing import Any

from libs.subflow.config import Settings
from libs.subflow.models.segment import ASRSegment, SemanticChunk
from libs.subflow.stages.base import Stage


class GlobalUnderstandingPass(Stage):
    name = "llm_global_understanding"

    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("full_transcript"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        context = dict(context)
        transcript = str(context.get("full_transcript", ""))
        context["global_context"] = f"Mock summary: {transcript[:120]}"
        return context


class SemanticChunkingPass(Stage):
    name = "llm_semantic_chunking"

    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("asr_segments"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        context = dict(context)
        asr_segments: list[ASRSegment] = list(context.get("asr_segments", []))
        chunks: list[SemanticChunk] = []
        for segment in asr_segments:
            chunks.append(
                SemanticChunk(
                    id=segment.id,
                    text=segment.text,
                    start=segment.start,
                    end=segment.end,
                    source_segment_ids=[segment.id],
                )
            )
        context["semantic_chunks"] = chunks
        return context


class TranslationPass(Stage):
    name = "llm_translation"

    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("semantic_chunks")) and bool(context.get("target_language"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        context = dict(context)
        target_language = str(context.get("target_language", "zh"))
        chunks: list[SemanticChunk] = list(context.get("semantic_chunks", []))
        for chunk in chunks:
            chunk.translation = f"[{target_language}] {chunk.text}"
        context["semantic_chunks"] = chunks
        return context


class QAPass(Stage):
    name = "llm_qa"

    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("semantic_chunks"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        return dict(context)

