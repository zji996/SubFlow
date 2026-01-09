"""Projects API routes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from services.project_service import ProjectService
from subflow.config import Settings
from subflow.export import SubtitleExporter
from subflow.export.formatters.base import SubtitleFormatter, selected_lines
from subflow.models.subtitle_export import SubtitleExport, SubtitleExportSource
from subflow.models.project import Project, StageName
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk
from subflow.models.serializers import (
    deserialize_asr_corrected_segments,
    deserialize_asr_segments,
    deserialize_semantic_chunks,
)
from subflow.models.subtitle_types import (
    AssStyleConfig,
    SubtitleContent,
    SubtitleEntry,
    SubtitleExportConfig,
    SubtitleFormat,
    TranslationStyle,
)
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


class SubtitlePreviewEntry(BaseModel):
    index: int
    start: str
    end: str
    primary: str
    secondary: str


class SubtitlePreviewResponse(BaseModel):
    entries: list[SubtitlePreviewEntry]
    total: int


class CreateSubtitleExportEntry(BaseModel):
    start: float
    end: float
    primary_text: str = ""
    secondary_text: str = ""


class CreateSubtitleExportRequest(BaseModel):
    format: str = "srt"
    content: str = "both"
    primary_position: str = "top"
    translation_style: str = "per_chunk"
    ass_style: dict[str, Any] | None = None
    entries: list[CreateSubtitleExportEntry] | None = None


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


def _safe_filename_base(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {" ", "_", "-", "."})
    cleaned = "_".join(cleaned.strip().split())
    cleaned = cleaned.strip("._-")
    return cleaned[:80] or "subtitles"


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


def _export_download_url(project_id: str, export_id: str) -> str:
    return f"/projects/{project_id}/exports/{export_id}/download"


def _export_to_response(project_id: str, exp: SubtitleExport) -> SubtitleExportResponse:
    return SubtitleExportResponse(
        id=exp.id,
        created_at=exp.created_at,
        format=exp.format.value,
        content_mode=exp.content_mode.value,
        source=exp.source.value,
        download_url=_export_download_url(project_id, exp.id),
    )


def _export_to_detail_response(project_id: str, exp: SubtitleExport) -> SubtitleExportDetailResponse:
    return SubtitleExportDetailResponse(
        **_export_to_response(project_id, exp).model_dump(),
        config_json=exp.config_json,
        storage_key=exp.storage_key,
        entries_name=exp.entries_name,
    )


def _find_export(project: Project, export_id: str) -> SubtitleExport | None:
    for exp in list(project.exports or []):
        if exp.id == export_id:
            return exp
    return None


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
    if stage == StageName.EXPORT:
        raise HTTPException(status_code=400, detail="export stage has been removed")
    if stage is None:
        next_stage = max(0, int(project.current_stage)) + 1
        stage = {
            1: StageName.AUDIO_PREPROCESS,
            2: StageName.VAD,
            3: StageName.ASR,
            4: StageName.LLM_ASR_CORRECTION,
            5: StageName.LLM,
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


@router.get("/{project_id}/artifacts/{stage}/{artifact_name}")
async def get_artifact_content(
    request: Request,
    project_id: str,
    stage: StageName,
    artifact_name: str,
) -> dict[str, Any]:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    if "/" in artifact_name or "\\" in artifact_name or ".." in artifact_name:
        raise HTTPException(status_code=400, detail="invalid artifact name")

    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    store = get_artifact_store(settings)
    try:
        if artifact_name.endswith(".json"):
            data = await store.load_json(project_id, stage.value, artifact_name)
            return {
                "project_id": project_id,
                "stage": stage.value,
                "name": artifact_name,
                "kind": "json",
                "data": data,
            }
        text = await store.load_text(project_id, stage.value, artifact_name)
        return {
            "project_id": project_id,
            "stage": stage.value,
            "name": artifact_name,
            "kind": "text",
            "data": text,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="artifact not found") from None


@router.get("/{project_id}/exports", response_model=list[SubtitleExportResponse])
async def list_exports(request: Request, project_id: str) -> list[SubtitleExportResponse]:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    exports = list(project.exports or [])

    def _ts(value: datetime) -> float:
        try:
            return float(value.timestamp())
        except Exception:
            return 0.0

    exports.sort(key=lambda x: _ts(x.created_at), reverse=True)
    return [_export_to_response(project_id, exp) for exp in exports]


@router.post("/{project_id}/exports", response_model=SubtitleExportDetailResponse)
async def create_export(
    request: Request,
    project_id: str,
    payload: CreateSubtitleExportRequest,
) -> SubtitleExportDetailResponse:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    if int(project.current_stage) < 5:
        raise HTTPException(status_code=409, detail="请先完成 LLM 翻译阶段")

    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    try:
        fmt = SubtitleFormat(payload.format)
        content_mode = SubtitleContent(payload.content)
        translation_style = TranslationStyle(payload.translation_style)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.primary_position not in {"top", "bottom"}:
        raise HTTPException(status_code=400, detail="primary_position must be 'top' or 'bottom'")

    ass_style: AssStyleConfig | None = None
    ass_style_dict = payload.ass_style or {}
    if fmt == SubtitleFormat.ASS:
        default_style = AssStyleConfig()
        ass_style = AssStyleConfig(
            primary_font=str(ass_style_dict.get("primary_font") or default_style.primary_font),
            primary_size=int(ass_style_dict.get("primary_size") or default_style.primary_size),
            primary_color=str(ass_style_dict.get("primary_color") or default_style.primary_color),
            primary_outline_color=str(
                ass_style_dict.get("primary_outline_color") or default_style.primary_outline_color
            ),
            primary_outline_width=int(
                ass_style_dict.get("primary_outline_width") or default_style.primary_outline_width
            ),
            secondary_font=str(ass_style_dict.get("secondary_font") or default_style.secondary_font),
            secondary_size=int(ass_style_dict.get("secondary_size") or default_style.secondary_size),
            secondary_color=str(ass_style_dict.get("secondary_color") or default_style.secondary_color),
            secondary_outline_color=str(
                ass_style_dict.get("secondary_outline_color") or default_style.secondary_outline_color
            ),
            secondary_outline_width=int(
                ass_style_dict.get("secondary_outline_width") or default_style.secondary_outline_width
            ),
            position=str(ass_style_dict.get("position") or default_style.position),
            margin=int(ass_style_dict.get("margin") or default_style.margin),
        )

    config = SubtitleExportConfig(
        format=fmt,
        content=content_mode,
        primary_position=payload.primary_position,
        translation_style=translation_style,
        ass_style=ass_style,
    )

    entries_name: str | None = None
    entries_key: str | None = None
    source = SubtitleExportSource.AUTO

    if payload.entries:
        source = SubtitleExportSource.EDITED
        items: list[tuple[float, float, int, str, str]] = []
        for i, e in enumerate(payload.entries):
            start = float(e.start)
            end = float(e.end)
            if end < start:
                start, end = end, start
            items.append(
                (
                    start,
                    end,
                    i,
                    str(e.primary_text or "").strip(),
                    str(e.secondary_text or "").strip(),
                )
            )
        items.sort(key=lambda x: (x[0], x[1], x[2]))
        entries: list[SubtitleEntry] = []
        for idx, (start, end, _, primary, secondary) in enumerate(items, start=1):
            entries.append(
                SubtitleEntry(
                    index=idx,
                    start=float(start),
                    end=float(end),
                    primary_text=primary,
                    secondary_text=secondary,
                )
            )
        subtitle_text = SubtitleExporter().export_entries(entries, config)
    else:
        chunks, asr_segments, corrected = await _load_subtitle_materials(settings, project)
        if not asr_segments:
            raise HTTPException(status_code=404, detail="ASR 数据不存在")
        subtitle_text = SubtitleExporter().export(
            chunks=chunks,
            asr_segments=asr_segments,
            asr_corrected_segments=corrected,
            config=config,
        )

    store = get_artifact_store(settings)
    export_id = f"export_{uuid4().hex}"
    storage_stage = "exports"
    storage_name = f"{export_id}.{fmt.value}"
    storage_key = await store.save_text(project_id, storage_stage, storage_name, subtitle_text)

    if payload.entries:
        entries_name = f"{export_id}.entries.json"
        entries_payload = [
            {
                "index": int(e.index),
                "start": float(e.start),
                "end": float(e.end),
                "primary_text": str(e.primary_text or ""),
                "secondary_text": str(e.secondary_text or ""),
            }
            for e in entries
        ]
        entries_key = await store.save_json(project_id, storage_stage, entries_name, entries_payload)

    config_json = json.dumps(
        {
            "format": fmt.value,
            "content_mode": content_mode.value,
            "primary_position": payload.primary_position,
            "translation_style": translation_style.value,
            "ass_style": ass_style_dict if fmt == SubtitleFormat.ASS else None,
        },
        ensure_ascii=False,
    )

    exp = SubtitleExport(
        id=export_id,
        project_id=project_id,
        created_at=datetime.now(tz=timezone.utc),
        format=fmt,
        content_mode=content_mode,
        config_json=config_json,
        storage_stage=storage_stage,
        storage_name=storage_name,
        storage_key=storage_key,
        source=source,
        entries_name=entries_name,
        entries_key=entries_key,
    )
    project.exports.append(exp)
    await service.save_project(project)
    return _export_to_detail_response(project_id, exp)


@router.get("/{project_id}/exports/{export_id}", response_model=SubtitleExportDetailResponse)
async def get_export(request: Request, project_id: str, export_id: str) -> SubtitleExportDetailResponse:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    exp = _find_export(project, export_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="export not found")
    return _export_to_detail_response(project_id, exp)


@router.get("/{project_id}/exports/{export_id}/download")
async def download_export(request: Request, project_id: str, export_id: str) -> Response:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    exp = _find_export(project, export_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="export not found")

    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    store = get_artifact_store(settings)
    try:
        data = await store.load(project_id, exp.storage_stage, exp.storage_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="export file not found") from None
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to load export: {exc}") from exc

    media_type = {
        "srt": "text/plain; charset=utf-8",
        "vtt": "text/vtt; charset=utf-8",
        "ass": "text/plain; charset=utf-8",
        "json": "application/json; charset=utf-8",
    }.get(exp.format.value, "text/plain; charset=utf-8")

    base_name = _safe_filename_base(str(project.name or "subtitles"))
    ascii_base = base_name.encode("ascii", "ignore").decode("ascii") or "subtitles"
    filename = f"{base_name}_{export_id}.{exp.format.value}"
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_base}_{export_id}.{exp.format.value}"; '
            f"filename*=UTF-8''{quote(filename)}"
        ),
    }
    return Response(content=data, media_type=media_type, headers=headers)


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

    if int(project.current_stage) < 5:
        raise HTTPException(status_code=409, detail="请先完成 LLM 翻译阶段")

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
        raise HTTPException(status_code=404, detail="ASR 数据不存在")

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

    base_name = _safe_filename_base(str(project.name or "subtitles"))
    ascii_base = base_name.encode("ascii", "ignore").decode("ascii") or "subtitles"
    filename = f"{base_name}.{fmt.value}"
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_base}.{fmt.value}"; filename*=UTF-8\'\'{quote(filename)}'
        ),
    }
    return Response(content=subtitle_text, media_type=media_type, headers=headers)


@router.delete("/{project_id}")
async def delete_project(request: Request, project_id: str) -> dict:
    service = _service(request)
    ok = await service.delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="project not found")
    return {"deleted": True, "project_id": project_id}
