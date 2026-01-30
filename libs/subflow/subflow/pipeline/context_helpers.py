"""Typed helpers for accessing PipelineContext values.

Prefer these helpers over direct string-key indexing to keep type checkers and
IDEs useful while retaining a dict-based PipelineContext.
"""

from __future__ import annotations

from subflow.models.segment import ASRSegment, SemanticChunk, VADSegment
from subflow.pipeline.context import PipelineContext


def get_asr_segments(ctx: PipelineContext) -> list[ASRSegment]:
    return list(ctx.get("asr_segments") or [])


def get_vad_regions(ctx: PipelineContext) -> list[VADSegment]:
    return list(ctx.get("vad_regions") or [])


def get_semantic_chunks(ctx: PipelineContext) -> list[SemanticChunk]:
    return list(ctx.get("semantic_chunks") or [])

