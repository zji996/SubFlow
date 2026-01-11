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
from psycopg_pool import AsyncConnectionPool

from services.project_service import ProjectService
from subflow.config import Settings
from subflow.export import SubtitleExporter
from subflow.export.formatters.base import SubtitleFormatter, selected_lines
from subflow.models.subtitle_export import SubtitleExport, SubtitleExportSource
from subflow.models.project import Project, StageName
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk
from subflow.models.serializers import serialize_asr_segments, serialize_semantic_chunks
from subflow.models.subtitle_types import (
    AssStyleConfig,
    SubtitleContent,
    SubtitleEntry,
    SubtitleExportConfig,
    SubtitleFormat,
    TranslationStyle,
)
from subflow.repositories import (
    ASRSegmentRepository,
    SemanticChunkRepository,
    StageRunRepository,
    SubtitleExportRepository,
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


class SubtitleEditComputedEntry(BaseModel):
    segment_id: int
    start: float
    end: float
    secondary: str
    primary_per_chunk: str
    primary_full: str
    primary_per_segment: str
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


def _safe_filename_base(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {" ", "_", "-", "."})
    cleaned = "_".join(cleaned.strip().split())
    cleaned = cleaned.strip("._-")
    return cleaned[:80] or "subtitles"


def _service(request: Request) -> ProjectService:
    redis: Redis = request.app.state.redis
    settings: Settings = request.app.state.settings
    pool: AsyncConnectionPool | None = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=500, detail="db pool not initialized")
    return ProjectService(redis=redis, settings=settings, pool=pool)


def _pool(request: Request) -> AsyncConnectionPool:
    pool: AsyncConnectionPool | None = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=500, detail="db pool not initialized")
    return pool


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
    pool: AsyncConnectionPool,
    project_id: str,
) -> tuple[list[SemanticChunk], list[ASRSegment], dict[int, ASRCorrectedSegment] | None]:
    asr_repo = ASRSegmentRepository(pool)
    semantic_chunk_repo = SemanticChunkRepository(pool)
    asr_segments = await asr_repo.get_by_project(project_id, use_corrected=False)
    corrections = await asr_repo.get_corrected_map(project_id)
    corrected: dict[int, ASRCorrectedSegment] | None = None
    if corrections:
        corrected = {
            int(seg_id): ASRCorrectedSegment(id=int(seg_id), asr_segment_id=int(seg_id), text=str(text or ""))
            for seg_id, text in corrections.items()
        }
    chunks = await semantic_chunk_repo.get_by_project(project_id)
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
    stage_run_repo = StageRunRepository(_pool(request))
    sr = await stage_run_repo.get(project_id, stage.value)
    return {
        "project_id": project_id,
        "stage": stage.value,
        "artifacts": dict(sr.output_artifacts or {}) if sr is not None else {},
    }


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
    generated_entries: list[SubtitleEntry] | None = None
    generated_segment_ids: list[int] | None = None

    if payload.entries and payload.edited_entries:
        raise HTTPException(status_code=400, detail="entries and edited_entries are mutually exclusive")

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
        generated_entries = entries
        subtitle_text = SubtitleExporter().export_entries(generated_entries, config)
    elif payload.edited_entries:
        source = SubtitleExportSource.EDITED
        chunks, asr_segments, corrected = await _load_subtitle_materials(_pool(request), project_id)
        if not asr_segments:
            raise HTTPException(status_code=404, detail="ASR 数据不存在")

        corrected_by_asr_id: dict[int, ASRCorrectedSegment] = {}
        for seg in list((corrected or {}).values()):
            corrected_by_asr_id[int(seg.asr_segment_id)] = seg

        chunk_by_segment_id: dict[int, SemanticChunk] = {}
        for semantic_chunk in chunks:
            for seg_id in list(semantic_chunk.asr_segment_ids or []):
                chunk_by_segment_id.setdefault(int(seg_id), semantic_chunk)

        per_chunk_translation: dict[int, str] = {}
        translation_chunk_key_by_segment_id: dict[int, tuple[int, int]] = {}
        for semantic_chunk in chunks:
            for idx, ch in enumerate(list(semantic_chunk.translation_chunks or [])):
                key = (int(semantic_chunk.id), int(idx))
                for seg_id in list(ch.segment_ids or []):
                    per_chunk_translation.setdefault(int(seg_id), str(ch.text or "").strip())
                    translation_chunk_key_by_segment_id.setdefault(int(seg_id), key)

        ordered_segments = sorted(asr_segments, key=lambda s: (float(s.start), float(s.end), int(s.id)))
        segment_order = {int(seg.id): i for i, seg in enumerate(ordered_segments)}

        per_segment_translation: dict[int, str] = {}
        for semantic_chunk in chunks:
            seg_ids = [int(x) for x in list(semantic_chunk.asr_segment_ids or [])]
            seg_ids_in_order = [sid for sid in seg_ids if sid in segment_order]
            seg_ids_in_order.sort(key=lambda sid: segment_order[sid])
            if not seg_ids_in_order:
                continue
            slices = _split_text_evenly(str(semantic_chunk.translation or "").strip(), len(seg_ids_in_order))
            for sid, piece in zip(seg_ids_in_order, slices, strict=False):
                per_segment_translation[int(sid)] = str(piece).strip()

        def _primary_group_key(segment_id: int) -> tuple[str, int, int] | tuple[str, int]:
            seg_id = int(segment_id)
            match translation_style:
                case TranslationStyle.PER_CHUNK:
                    if seg_id in translation_chunk_key_by_segment_id:
                        scid, idx = translation_chunk_key_by_segment_id[seg_id]
                        return ("translation_chunk", int(scid), int(idx))
                    return ("segment", seg_id)
                case TranslationStyle.FULL:
                    chunk = chunk_by_segment_id.get(seg_id)
                    if chunk is not None:
                        return ("semantic_chunk", int(chunk.id))
                    return ("segment", seg_id)
                case _:
                    return ("segment", seg_id)

        primary_override_by_group: dict[tuple[str, int, int] | tuple[str, int], str] = {}
        secondary_override_by_segment: dict[int, str] = {}
        known_segment_ids = set(segment_order.keys())

        for edited in payload.edited_entries:
            seg_id = int(edited.segment_id)
            if seg_id not in known_segment_ids:
                raise HTTPException(status_code=400, detail=f"unknown segment_id: {seg_id}")
            if edited.secondary is not None:
                secondary_override_by_segment[seg_id] = str(edited.secondary)
            if edited.primary is not None:
                primary_override_by_group[_primary_group_key(seg_id)] = str(edited.primary)

        items: list[tuple[float, float, int, str, str]] = []
        for seg in ordered_segments:
            seg_id = int(seg.id)
            corrected_seg = corrected_by_asr_id.get(seg_id)
            secondary = (
                (str(corrected_seg.text).strip() if corrected_seg is not None else "")
                or str(seg.text or "").strip()
            )

            match translation_style:
                case TranslationStyle.PER_CHUNK:
                    primary = str(per_chunk_translation.get(seg_id, "") or "").strip()
                case TranslationStyle.FULL:
                    chunk_for_seg = chunk_by_segment_id.get(seg_id)
                    primary = str((chunk_for_seg.translation if chunk_for_seg is not None else "") or "").strip()
                case _:
                    primary = str(per_segment_translation.get(seg_id, "") or "").strip()

            primary = primary_override_by_group.get(_primary_group_key(seg_id), primary)
            secondary = secondary_override_by_segment.get(seg_id, secondary)

            if not primary and not secondary:
                continue
            start, end = float(seg.start), float(seg.end)
            items.append((start, end, seg_id, primary, secondary))

        items.sort(key=lambda x: (x[0], x[1], x[2]))
        generated_entries = []
        generated_segment_ids = []
        for idx, (start, end, _, primary, secondary) in enumerate(items, start=1):
            generated_segment_ids.append(int(_))
            generated_entries.append(
                SubtitleEntry(
                    index=idx,
                    start=float(start),
                    end=float(end),
                    primary_text=str(primary or "").strip(),
                    secondary_text=str(secondary or "").strip(),
                )
            )

        subtitle_text = SubtitleExporter().export_entries(generated_entries, config)
    else:
        chunks, asr_segments, corrected = await _load_subtitle_materials(_pool(request), project_id)
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

    if generated_entries is not None:
        entries_name = f"{export_id}.entries.json"
        if payload.entries:
            entries_payload = [
                {
                    "index": int(e.index),
                    "start": float(e.start),
                    "end": float(e.end),
                    "primary_text": str(e.primary_text or ""),
                    "secondary_text": str(e.secondary_text or ""),
                }
                for e in generated_entries
            ]
        else:
            segment_ids = list(generated_segment_ids or [])
            entries_payload = [
                {
                    "segment_id": int(segment_ids[i - 1]),
                    "index": int(e.index),
                    "start": float(e.start),
                    "end": float(e.end),
                    "primary_text": str(e.primary_text or ""),
                    "secondary_text": str(e.secondary_text or ""),
                }
                for i, e in enumerate(generated_entries, start=1)
            ]
        entries_key = await store.save_json(project_id, storage_stage, entries_name, entries_payload)

    config_json = json.dumps(
        {
            "format": fmt.value,
            "content_mode": content_mode.value,
            "primary_position": payload.primary_position,
            "translation_style": translation_style.value,
            "ass_style": ass_style_dict if fmt == SubtitleFormat.ASS else None,
            "has_entries": bool(generated_entries is not None),
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
    exp_repo = SubtitleExportRepository(_pool(request))
    exp = await exp_repo.create(exp)
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

    chunks, asr_segments, corrected = await _load_subtitle_materials(_pool(request), project_id)
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


def _split_text_evenly(text: str, parts: int) -> list[str]:
    cleaned = str(text or "")
    if parts <= 0:
        return []
    if parts == 1:
        return [cleaned]
    n = len(cleaned)
    out: list[str] = []
    for i in range(parts):
        start = round(i * n / parts)
        end = round((i + 1) * n / parts)
        out.append(cleaned[start:end])
    return out


@router.get("/{project_id}/subtitles/edit-data", response_model=SubtitleEditDataResponse)
async def get_subtitle_edit_data(request: Request, project_id: str) -> SubtitleEditDataResponse:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    chunks, asr_segments, corrected = await _load_subtitle_materials(_pool(request), project_id)
    if not asr_segments:
        raise HTTPException(status_code=404, detail="ASR 数据不存在")

    corrected_by_asr_id: dict[int, ASRCorrectedSegment] = {}
    for seg in list((corrected or {}).values()):
        corrected_by_asr_id[int(seg.asr_segment_id)] = seg

    chunk_by_segment_id: dict[int, SemanticChunk] = {}
    for semantic_chunk in chunks:
        for seg_id in list(semantic_chunk.asr_segment_ids or []):
            chunk_by_segment_id.setdefault(int(seg_id), semantic_chunk)

    per_chunk_translation: dict[int, str] = {}
    for semantic_chunk in chunks:
        for ch in list(semantic_chunk.translation_chunks or []):
            for seg_id in list(ch.segment_ids or []):
                per_chunk_translation.setdefault(int(seg_id), str(ch.text or "").strip())

    segment_order: dict[int, int] = {}
    ordered_segments = sorted(asr_segments, key=lambda s: (float(s.start), float(s.end), int(s.id)))
    for i, seg in enumerate(ordered_segments):
        segment_order[int(seg.id)] = i

    per_segment_translation: dict[int, str] = {}
    for semantic_chunk in chunks:
        seg_ids = [int(x) for x in list(semantic_chunk.asr_segment_ids or [])]
        seg_ids_in_order = [sid for sid in seg_ids if sid in segment_order]
        seg_ids_in_order.sort(key=lambda sid: segment_order[sid])
        if not seg_ids_in_order:
            continue
        slices = _split_text_evenly(str(semantic_chunk.translation or "").strip(), len(seg_ids_in_order))
        for sid, piece in zip(seg_ids_in_order, slices, strict=False):
            per_segment_translation[int(sid)] = str(piece).strip()

    computed: list[SubtitleEditComputedEntry] = []
    for seg in ordered_segments:
        corrected_seg = corrected_by_asr_id.get(int(seg.id))
        secondary = (str(corrected_seg.text).strip() if corrected_seg is not None else "") or str(seg.text or "").strip()
        chunk_for_seg = chunk_by_segment_id.get(int(seg.id))
        semantic_chunk_id = int(chunk_for_seg.id) if chunk_for_seg is not None else None
        computed.append(
            SubtitleEditComputedEntry(
                segment_id=int(seg.id),
                start=float(seg.start),
                end=float(seg.end),
                secondary=secondary,
                primary_per_chunk=str(per_chunk_translation.get(int(seg.id), "") or "").strip(),
                primary_full=str((chunk_for_seg.translation if chunk_for_seg is not None else "") or "").strip(),
                primary_per_segment=str(per_segment_translation.get(int(seg.id), "") or "").strip(),
                semantic_chunk_id=semantic_chunk_id,
            )
        )

    return SubtitleEditDataResponse(
        asr_segments=serialize_asr_segments(ordered_segments),
        asr_corrected_segments={
            int(asr_id): {"id": int(seg.id), "asr_segment_id": int(seg.asr_segment_id), "text": seg.text}
            for asr_id, seg in corrected_by_asr_id.items()
        },
        semantic_chunks=serialize_semantic_chunks(chunks),
        computed_entries=computed,
    )


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

    chunks, asr_segments, corrected = await _load_subtitle_materials(_pool(request), project_id)
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
