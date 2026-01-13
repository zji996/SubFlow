from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

from fastapi import HTTPException, Request
from redis.asyncio import Redis

from services.project_service import ProjectService
from subflow.config import Settings
from subflow.models.project import Project
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk
from subflow.models.subtitle_export import SubtitleExport

from .schemas import ProjectResponse, SubtitleExportDetailResponse, SubtitleExportResponse


def _projects_module() -> Any:
    module = sys.modules.get("routes.projects")
    if module is None:
        raise RuntimeError("routes.projects module not loaded")
    return module


def safe_filename_base(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {" ", "_", "-", "."})
    cleaned = "_".join(cleaned.strip().split())
    cleaned = cleaned.strip("._-")
    return cleaned[:80] or "subtitles"


def service(request: Request) -> ProjectService:
    redis: Redis = request.app.state.redis
    settings: Settings = request.app.state.settings
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=500, detail="db pool not initialized")
    return ProjectService(redis=redis, settings=settings, pool=pool)


def pool(request: Request):
    pool_obj = getattr(request.app.state, "db_pool", None)
    if pool_obj is None:
        raise HTTPException(status_code=500, detail="db pool not initialized")
    return pool_obj


def to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        media_url=project.media_url,
        source_language=project.source_language,
        target_language=project.target_language,
        auto_workflow=bool(project.auto_workflow),
        status=project.status.value,
        current_stage=int(project.current_stage),
        artifacts=dict(project.artifacts or {}),
        stage_runs=[sr.to_dict() for sr in list(project.stage_runs or [])],
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def export_download_url(project_id: str, export_id: str) -> str:
    return f"/api/projects/{project_id}/exports/{export_id}/download"


def export_to_response(project_id: str, exp: SubtitleExport) -> SubtitleExportResponse:
    return SubtitleExportResponse(
        id=exp.id,
        created_at=exp.created_at,
        format=exp.format.value,
        content_mode=exp.content_mode.value,
        source=exp.source.value,
        download_url=export_download_url(project_id, exp.id),
    )


def export_to_detail_response(project_id: str, exp: SubtitleExport) -> SubtitleExportDetailResponse:
    return SubtitleExportDetailResponse(
        **export_to_response(project_id, exp).model_dump(),
        config_json=exp.config_json,
        storage_key=exp.storage_key,
        entries_name=exp.entries_name,
    )


def find_export(project: Project, export_id: str) -> SubtitleExport | None:
    for exp in list(project.exports or []):
        if exp.id == export_id:
            return exp
    return None


async def load_subtitle_materials(
    pool_obj,
    project_id: str,
) -> tuple[list[SemanticChunk], list[ASRSegment], dict[int, ASRCorrectedSegment] | None]:
    projects_module = _projects_module()
    asr_repo = projects_module.ASRSegmentRepository(pool_obj)
    semantic_chunk_repo = projects_module.SemanticChunkRepository(pool_obj)
    asr_segments = await asr_repo.get_by_project(project_id, use_corrected=False)
    corrections = await asr_repo.get_corrected_map(project_id)
    corrected: dict[int, ASRCorrectedSegment] | None = None
    if corrections:
        corrected = {
            int(seg_id): ASRCorrectedSegment(
                id=int(seg_id), asr_segment_id=int(seg_id), text=str(text or "")
            )
            for seg_id, text in corrections.items()
        }
    chunks = await semantic_chunk_repo.get_by_project(project_id)
    return chunks, asr_segments, corrected


def sortable_timestamp(value: datetime) -> float:
    try:
        return float(value.timestamp())
    except Exception:
        return 0.0
