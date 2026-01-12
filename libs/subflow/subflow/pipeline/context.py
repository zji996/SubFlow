"""Pipeline context typing.

The pipeline uses a shared context dict passed between stages. This module
defines the stable, known keys to improve type safety and readability.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable

from subflow.models.segment import ASRCorrectedSegment, ASRMergedChunk, ASRSegment, SemanticChunk, VADSegment


class ProgressReporter(Protocol):
    async def report(self, progress: int, message: str) -> None: ...


class StageMetrics(TypedDict, total=False):
    progress: int
    progress_message: str

    items_processed: int
    items_total: int
    items_per_second: float

    llm_prompt_tokens: int
    llm_completion_tokens: int
    llm_tokens_per_second: float
    llm_calls_count: int

    active_tasks: int
    max_concurrent: int


@runtime_checkable
class MetricsProgressReporter(ProgressReporter, Protocol):
    async def report_metrics(self, metrics: StageMetrics) -> None: ...


class PipelineContext(TypedDict, total=False):
    project_id: str
    job_id: str
    media_url: str
    video_url: str
    source_language: str | None
    target_language: str

    video_path: str
    audio_path: str
    vocals_audio_path: str

    vad_segments: list[VADSegment]
    vad_regions: list[VADSegment]

    asr_segments: list[ASRSegment]
    asr_segments_index: dict[int, ASRSegment]
    full_transcript: str
    asr_merged_chunks: list[ASRMergedChunk]

    global_context: dict[str, Any]
    topic: str
    domain: str
    style: str
    glossary: dict[str, str]
    translation_notes: list[str]
    asr_corrected_segments: dict[int, ASRCorrectedSegment]
    semantic_chunks: list[SemanticChunk]

    subtitle_text: str
    result_path: str
