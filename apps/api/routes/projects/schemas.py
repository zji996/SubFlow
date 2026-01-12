from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from subflow.models.project import StageName


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = "Untitled"
    media_url: str
    source_language: str | None = Field(default=None, alias="language")
    target_language: str
    auto_workflow: bool = True


class RunStageRequest(BaseModel):
    stage: StageName | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    media_url: str
    source_language: str | None = None
    target_language: str
    auto_workflow: bool
    status: str
    current_stage: int
    artifacts: dict
    stage_runs: list[dict]
    created_at: datetime
    updated_at: datetime


class PreviewStats(BaseModel):
    vad_region_count: int = 0
    asr_segment_count: int = 0
    corrected_count: int = 0
    semantic_chunk_count: int = 0
    total_duration_s: float = 0.0


class VADRegionPreview(BaseModel):
    region_id: int
    start: float
    end: float
    segment_count: int


class ProjectPreviewResponse(BaseModel):
    project: ProjectResponse
    global_context: dict[str, Any] = Field(default_factory=dict)
    stats: PreviewStats
    vad_regions: list[VADRegionPreview] = Field(default_factory=list)


class PreviewSemanticChunk(BaseModel):
    id: int
    text: str
    translation: str
    translation_chunk_text: str = ""


class PreviewSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    corrected_text: str | None = None
    semantic_chunk: PreviewSemanticChunk | None = None


class PreviewSegmentsResponse(BaseModel):
    total: int
    segments: list[PreviewSegment]


class SubtitlePreviewEntry(BaseModel):
    index: int
    start: str
    end: str
    primary: str
    secondary: str


class SubtitlePreviewResponse(BaseModel):
    entries: list[SubtitlePreviewEntry]
    total: int


class SubtitleEditComputedEntry(BaseModel):
    segment_id: int
    start: float
    end: float
    secondary: str
    primary_per_chunk: str
    primary_full: str
    semantic_chunk_id: int | None = None


class SubtitleEditDataResponse(BaseModel):
    asr_segments: list[dict[str, Any]]
    asr_corrected_segments: dict[int, dict[str, Any]]
    semantic_chunks: list[dict[str, Any]]
    computed_entries: list[SubtitleEditComputedEntry]


class CreateSubtitleExportEntry(BaseModel):
    start: float
    end: float
    primary_text: str = ""
    secondary_text: str = ""


class EditedSubtitleExportEntry(BaseModel):
    segment_id: int
    secondary: str | None = None
    primary: str | None = None


class CreateSubtitleExportRequest(BaseModel):
    format: str = "srt"
    content: str = "both"
    primary_position: str = "top"
    translation_style: str = "per_chunk"
    ass_style: dict[str, Any] | None = None
    entries: list[CreateSubtitleExportEntry] | None = None
    edited_entries: list[EditedSubtitleExportEntry] | None = None


class SubtitleExportResponse(BaseModel):
    id: str
    created_at: datetime
    format: str
    content_mode: str
    source: str
    download_url: str


class SubtitleExportDetailResponse(SubtitleExportResponse):
    config_json: str
    storage_key: str
    entries_name: str | None = None
