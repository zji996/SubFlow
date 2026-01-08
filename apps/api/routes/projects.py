"""Projects API routes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from services.project_service import ProjectService
from subflow.config import Settings
from subflow.export import SubtitleExporter
from subflow.export.formatters.base import SubtitleFormatter, selected_lines
from subflow.models.project import Project, StageName
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk
from subflow.models.serializers import (
    deserialize_asr_corrected_segments,
    deserialize_asr_segments,
    deserialize_semantic_chunks,
)
from subflow.models.subtitle_types import AssStyleConfig, SubtitleContent, SubtitleExportConfig, SubtitleFormat
from subflow.storage import get_artifact_store

router = APIRouter(prefix="/projects", tags=["projects"])


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


class SubtitleResponse(BaseModel):
    format: str = "srt"
    source: str
    content: str


class SubtitlePreviewEntry(BaseModel):
    index: int
    start: str
    end: str
    primary: str
    secondary: str


class SubtitlePreviewResponse(BaseModel):
    entries: list[SubtitlePreviewEntry]
    total: int


def _service(request: Request) -> ProjectService:
    redis: Redis = request.app.state.redis
    settings: Settings = request.app.state.settings
    return ProjectService(redis=redis, settings=settings)


def _to_response(project: Project) -> ProjectResponse:
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


async def _load_subtitle_materials(
    settings: Settings,
    project: Project,
) -> tuple[list[SemanticChunk], list[ASRSegment], dict[int, ASRCorrectedSegment] | None]:
    store = get_artifact_store(settings)

    asr_segments: list[ASRSegment] = []
    try:
        raw_asr = await store.load_json(project.id, StageName.ASR.value, "asr_segments.json")
        if isinstance(raw_asr, list):
            asr_segments = deserialize_asr_segments(raw_asr)
    except FileNotFoundError:
        pass

    corrected: dict[int, ASRCorrectedSegment] | None = None
    try:
        raw_corrected = await store.load_json(
            project.id,
            StageName.LLM_ASR_CORRECTION.value,
            "asr_corrected_segments.json",
        )
        if isinstance(raw_corrected, list):
            corrected = deserialize_asr_corrected_segments(raw_corrected)
    except FileNotFoundError:
        try:
            raw_corrected = await store.load_json(
                project.id,
                StageName.LLM.value,
                "asr_corrected_segments.json",
            )
            if isinstance(raw_corrected, list):
                corrected = deserialize_asr_corrected_segments(raw_corrected)
        except FileNotFoundError:
            pass

    chunks: list[SemanticChunk] = []
    try:
        raw_chunks = await store.load_json(project.id, StageName.LLM.value, "semantic_chunks.json")
        if isinstance(raw_chunks, list):
            chunks = deserialize_semantic_chunks(raw_chunks)
    except FileNotFoundError:
        pass

    return chunks, asr_segments, corrected


@router.post("", response_model=ProjectResponse)
async def create_project(request: Request, payload: CreateProjectRequest) -> ProjectResponse:
    service = _service(request)
    project = await service.create_project(
        name=payload.name,
        media_url=payload.media_url,
        source_language=payload.source_language,
        target_language=payload.target_language,
        auto_workflow=payload.auto_workflow,
    )
    return _to_response(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(request: Request) -> list[ProjectResponse]:
    service = _service(request)
    projects = await service.list_projects()
    return [_to_response(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(request: Request, project_id: str) -> ProjectResponse:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return _to_response(project)


@router.post("/{project_id}/run", response_model=ProjectResponse)
async def run_project(request: Request, project_id: str, payload: RunStageRequest) -> ProjectResponse:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    stage = payload.stage
    if stage is None:
        next_stage = max(0, int(project.current_stage)) + 1
        stage = {
            1: StageName.AUDIO_PREPROCESS,
            2: StageName.VAD,
            3: StageName.ASR,
            4: StageName.LLM_ASR_CORRECTION,
            5: StageName.LLM,
            6: StageName.EXPORT,
        }.get(next_stage)
        if stage is None:
            raise HTTPException(status_code=409, detail="project already completed")

    await service.enqueue_run_stage(project_id, stage)
    return _to_response(project)


@router.post("/{project_id}/run-all", response_model=ProjectResponse)
async def run_all(request: Request, project_id: str) -> ProjectResponse:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    await service.enqueue_run_all(project_id)
    return _to_response(project)


@router.get("/{project_id}/artifacts/{stage}")
async def get_artifacts(request: Request, project_id: str, stage: StageName) -> dict:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    artifacts = dict(project.artifacts or {})
    return {"project_id": project_id, "stage": stage.value, "artifacts": artifacts.get(stage.value)}


@router.get("/{project_id}/subtitles", response_model=SubtitleResponse)
async def get_subtitles(request: Request, project_id: str) -> SubtitleResponse:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    export: dict[str, Any] = (project.artifacts or {}).get(StageName.EXPORT.value) or {}
    local_path = export.get("subtitles.srt")
    presigned_url = export.get("subtitles.srt_url")

    settings: Settings | None = getattr(request.app.state, "settings", None)
    data_root = Path(settings.data_dir).resolve() if settings is not None else None

    if local_path:
        try:
            path = Path(str(local_path)).expanduser().resolve()
            if data_root is not None and path != data_root and data_root not in path.parents:
                raise HTTPException(status_code=400, detail="invalid subtitles path")
            content = path.read_text(encoding="utf-8", errors="replace")
            return SubtitleResponse(source="local", content=content)
        except FileNotFoundError:
            pass
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to read subtitles: {exc}") from exc

    if presigned_url:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(str(presigned_url))
                resp.raise_for_status()
                return SubtitleResponse(source="s3", content=resp.text)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"failed to fetch subtitles: {exc}") from exc

    raise HTTPException(status_code=404, detail="subtitles not found")


@router.get("/{project_id}/subtitles/preview", response_model=SubtitlePreviewResponse)
async def preview_subtitles(
    request: Request,
    project_id: str,
    format: str = Query(default="srt", pattern="^(srt|vtt|ass|json)$"),
    content: str = Query(default="both", pattern="^(both|primary_only|secondary_only)$"),
    primary_position: str = Query(default="top", pattern="^(top|bottom)$"),
) -> SubtitlePreviewResponse:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    try:
        fmt = SubtitleFormat(format)
        content_mode = SubtitleContent(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    chunks, asr_segments, corrected = await _load_subtitle_materials(settings, project)
    if not asr_segments:
        raise HTTPException(status_code=404, detail="asr segments not found")

    config = SubtitleExportConfig(format=fmt, content=content_mode, primary_position=primary_position)
    entries = SubtitleExporter().build_entries(
        chunks=chunks,
        asr_segments=asr_segments,
        asr_corrected_segments=corrected,
    )

    out: list[SubtitlePreviewEntry] = []
    for entry in entries:
        rendered = selected_lines(entry.primary_text, entry.secondary_text, config)
        primary_text = ""
        secondary_text = ""
        for kind, text in rendered:
            if kind == "primary":
                primary_text = text
            else:
                secondary_text = text
        out.append(
            SubtitlePreviewEntry(
                index=int(entry.index),
                start=SubtitleFormatter.seconds_to_timestamp(entry.start, ","),
                end=SubtitleFormatter.seconds_to_timestamp(entry.end, ","),
                primary=primary_text,
                secondary=secondary_text,
            )
        )

    return SubtitlePreviewResponse(entries=out, total=len(out))


@router.get("/{project_id}/subtitles/download")
async def download_subtitles(
    request: Request,
    project_id: str,
    format: str = Query(default="srt", pattern="^(srt|vtt|ass|json)$"),
    content: str = Query(default="both", pattern="^(both|primary_only|secondary_only)$"),
    primary_position: str = Query(default="top", pattern="^(top|bottom)$"),
    primary_font: str | None = None,
    primary_size: int | None = None,
    primary_color: str | None = None,
    primary_outline_color: str | None = None,
    primary_outline_width: int | None = None,
    secondary_font: str | None = None,
    secondary_size: int | None = None,
    secondary_color: str | None = None,
    secondary_outline_color: str | None = None,
    secondary_outline_width: int | None = None,
    position: str | None = None,
    margin: int | None = None,
) -> Response:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    try:
        fmt = SubtitleFormat(format)
        content_mode = SubtitleContent(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    chunks, asr_segments, corrected = await _load_subtitle_materials(settings, project)
    if not asr_segments:
        raise HTTPException(status_code=404, detail="asr segments not found")

    ass_style: AssStyleConfig | None = None
    if fmt == SubtitleFormat.ASS:
        default_style = AssStyleConfig()
        ass_style = AssStyleConfig(
            primary_font=primary_font or default_style.primary_font,
            primary_size=primary_size or default_style.primary_size,
            primary_color=primary_color or default_style.primary_color,
            primary_outline_color=primary_outline_color or default_style.primary_outline_color,
            primary_outline_width=primary_outline_width or default_style.primary_outline_width,
            secondary_font=secondary_font or default_style.secondary_font,
            secondary_size=secondary_size or default_style.secondary_size,
            secondary_color=secondary_color or default_style.secondary_color,
            secondary_outline_color=secondary_outline_color or default_style.secondary_outline_color,
            secondary_outline_width=secondary_outline_width or default_style.secondary_outline_width,
            position=position or default_style.position,
            margin=margin or default_style.margin,
        )

    config = SubtitleExportConfig(
        format=fmt,
        content=content_mode,
        primary_position=primary_position,
        ass_style=ass_style,
    )
    subtitle_text = SubtitleExporter().export(
        chunks=chunks,
        asr_segments=asr_segments,
        asr_corrected_segments=corrected,
        config=config,
    )

    media_type = {
        "srt": "text/plain; charset=utf-8",
        "vtt": "text/vtt; charset=utf-8",
        "ass": "text/plain; charset=utf-8",
        "json": "application/json; charset=utf-8",
    }.get(fmt.value, "text/plain; charset=utf-8")
    headers = {"Content-Disposition": f'attachment; filename="subtitles.{fmt.value}"'}
    return Response(content=subtitle_text, media_type=media_type, headers=headers)


@router.delete("/{project_id}")
async def delete_project(request: Request, project_id: str) -> dict:
    service = _service(request)
    ok = await service.delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="project not found")
    return {"deleted": True, "project_id": project_id}
