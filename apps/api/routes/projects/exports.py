from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from subflow.config import Settings
from subflow.export import SubtitleExporter
from subflow.models.segment import ASRCorrectedSegment, SemanticChunk
from subflow.models.subtitle_export import SubtitleExport, SubtitleExportSource
from subflow.models.subtitle_types import (
    AssStyleConfig,
    SubtitleContent,
    SubtitleEntry,
    SubtitleExportConfig,
    SubtitleFormat,
)
from subflow.storage import get_artifact_store

from ._deps import (
    _projects_module,
    export_to_detail_response,
    export_to_response,
    find_export,
    load_subtitle_materials,
    pool,
    safe_filename_base,
    service,
    sortable_timestamp,
)
from .schemas import (
    CreateSubtitleExportRequest,
    SubtitleExportDetailResponse,
    SubtitleExportResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{project_id}/exports", response_model=list[SubtitleExportResponse])
async def list_exports(request: Request, project_id: str) -> list[SubtitleExportResponse]:
    logger.info("list_exports start project_id=%s", project_id)
    try:
        project = await service(request).get_project(project_id)
    except Exception as exc:
        error_id = uuid4().hex
        logger.exception("list_exports failed project_id=%s error_id=%s", project_id, error_id)
        raise HTTPException(
            status_code=500, detail=f"获取导出列表失败（error_id={error_id}）"
        ) from exc
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    exports = list(project.exports or [])
    logger.info("list_exports ok project_id=%s count=%d", project_id, len(exports))

    exports.sort(key=lambda x: sortable_timestamp(x.created_at), reverse=True)
    return [export_to_response(project_id, exp) for exp in exports]


@router.post("/{project_id}/exports", response_model=SubtitleExportDetailResponse)
async def create_export(
    request: Request,
    project_id: str,
    payload: CreateSubtitleExportRequest,
) -> SubtitleExportDetailResponse:
    logger.info(
        "create_export start project_id=%s format=%s content=%s primary_position=%s entries=%s edited_entries=%s",
        project_id,
        str(payload.format),
        str(payload.content),
        str(payload.primary_position),
        int(len(payload.entries or [])),
        int(len(payload.edited_entries or [])),
    )
    try:
        project = await service(request).get_project(project_id)
    except Exception as exc:
        error_id = uuid4().hex
        logger.exception(
            "create_export failed to load project_id=%s error_id=%s", project_id, error_id
        )
        raise HTTPException(status_code=500, detail=f"创建导出失败（error_id={error_id}）") from exc
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    try:
        if int(project.current_stage) < 5:
            raise HTTPException(status_code=409, detail="请先完成 LLM 翻译阶段")

        fmt = SubtitleFormat(payload.format)
        content_mode = SubtitleContent(payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.primary_position not in {"top", "bottom"}:
        raise HTTPException(status_code=400, detail="primary_position must be 'top' or 'bottom'")

    try:
        ass_style: AssStyleConfig | None = None
        ass_style_dict = payload.ass_style or {}
        if fmt == SubtitleFormat.ASS:
            default_style = AssStyleConfig()
            ass_style = AssStyleConfig(
                primary_font=str(ass_style_dict.get("primary_font") or default_style.primary_font),
                primary_size=int(ass_style_dict.get("primary_size") or default_style.primary_size),
                primary_color=str(
                    ass_style_dict.get("primary_color") or default_style.primary_color
                ),
                primary_outline_color=str(
                    ass_style_dict.get("primary_outline_color")
                    or default_style.primary_outline_color
                ),
                primary_outline_width=int(
                    ass_style_dict.get("primary_outline_width")
                    or default_style.primary_outline_width
                ),
                secondary_font=str(
                    ass_style_dict.get("secondary_font") or default_style.secondary_font
                ),
                secondary_size=int(
                    ass_style_dict.get("secondary_size") or default_style.secondary_size
                ),
                secondary_color=str(
                    ass_style_dict.get("secondary_color") or default_style.secondary_color
                ),
                secondary_outline_color=str(
                    ass_style_dict.get("secondary_outline_color")
                    or default_style.secondary_outline_color
                ),
                secondary_outline_width=int(
                    ass_style_dict.get("secondary_outline_width")
                    or default_style.secondary_outline_width
                ),
                position=str(ass_style_dict.get("position") or default_style.position),
                margin=int(ass_style_dict.get("margin") or default_style.margin),
            )

        config = SubtitleExportConfig(
            format=fmt,
            content=content_mode,
            primary_position=payload.primary_position,
            ass_style=ass_style,
        )

        entries_name: str | None = None
        entries_key: str | None = None
        source = SubtitleExportSource.AUTO
        generated_entries: list[SubtitleEntry] | None = None
        generated_segment_ids: list[int] | None = None

        if payload.entries and payload.edited_entries:
            raise HTTPException(
                status_code=400, detail="entries and edited_entries are mutually exclusive"
            )

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
            chunks, asr_segments, corrected = await load_subtitle_materials(
                pool(request), project_id
            )
            if not asr_segments:
                raise HTTPException(status_code=404, detail="ASR 数据不存在")

            corrected_by_asr_id: dict[int, ASRCorrectedSegment] = {}
            for seg in list((corrected or {}).values()):
                corrected_by_asr_id[int(seg.asr_segment_id)] = seg

            chunk_by_segment_id: dict[int, SemanticChunk] = {}
            for semantic_chunk in chunks:
                for seg_id in list(semantic_chunk.asr_segment_ids or []):
                    chunk_by_segment_id.setdefault(int(seg_id), semantic_chunk)

            translation_by_segment_id: dict[int, str] = {}
            for semantic_chunk in chunks:
                for ch in list(semantic_chunk.translation_chunks or []):
                    seg_id = int(ch.segment_id)
                    translation_by_segment_id.setdefault(seg_id, str(ch.text or "").strip())
            for semantic_chunk in chunks:
                chunk_translation = str(semantic_chunk.translation or "").strip()
                if not chunk_translation:
                    continue
                for seg_id in list(semantic_chunk.asr_segment_ids or []):
                    translation_by_segment_id.setdefault(int(seg_id), chunk_translation)

            ordered_segments = sorted(
                asr_segments, key=lambda s: (float(s.start), float(s.end), int(s.id))
            )
            segment_order = {int(seg.id): i for i, seg in enumerate(ordered_segments)}

            primary_override_by_segment: dict[int, str] = {}
            secondary_override_by_segment: dict[int, str] = {}
            known_segment_ids = set(segment_order.keys())

            for edited in payload.edited_entries:
                seg_id = int(edited.segment_id)
                if seg_id not in known_segment_ids:
                    raise HTTPException(status_code=400, detail=f"unknown segment_id: {seg_id}")
                if edited.secondary is not None:
                    secondary_override_by_segment[seg_id] = str(edited.secondary)
                if edited.primary is not None:
                    primary_override_by_segment[seg_id] = str(edited.primary)

            items: list[tuple[float, float, int, int, str, str]] = []
            for seg in ordered_segments:
                seg_id = int(seg.id)
                corrected_seg = corrected_by_asr_id.get(seg_id)
                secondary = (
                    str(secondary_override_by_segment.get(seg_id, "")).strip()
                    if seg_id in secondary_override_by_segment
                    else (
                        (str(corrected_seg.text).strip() if corrected_seg is not None else "")
                        or str(seg.text or "").strip()
                    )
                )

                if seg_id in primary_override_by_segment:
                    primary = str(primary_override_by_segment[seg_id]).strip()
                else:
                    primary = str(translation_by_segment_id.get(seg_id, "") or "").strip()

                items.append(
                    (
                        float(seg.start),
                        float(seg.end),
                        segment_order[seg_id],
                        seg_id,
                        primary,
                        secondary,
                    )
                )
            items.sort(key=lambda x: (x[0], x[1], x[2]))

            generated_entries = []
            generated_segment_ids = []
            for idx, (start, end, _, seg_id, primary, secondary) in enumerate(items, start=1):
                generated_segment_ids.append(int(seg_id))
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
            chunks, asr_segments, corrected = await load_subtitle_materials(
                pool(request), project_id
            )
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
            entries_key = await store.save_json(
                project_id, storage_stage, entries_name, entries_payload
            )

        config_json = json.dumps(
            {
                "format": fmt.value,
                "content_mode": content_mode.value,
                "primary_position": payload.primary_position,
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

        projects_module = _projects_module()
        exp_repo = projects_module.SubtitleExportRepository(pool(request))
        exp = await exp_repo.create(exp)
    except HTTPException:
        raise
    except Exception as exc:
        error_id = uuid4().hex
        logger.exception("create_export failed project_id=%s error_id=%s", project_id, error_id)
        raise HTTPException(status_code=500, detail=f"创建导出失败（error_id={error_id}）") from exc

    logger.info("create_export ok project_id=%s export_id=%s", project_id, exp.id)
    return export_to_detail_response(project_id, exp)


@router.get("/{project_id}/exports/{export_id}", response_model=SubtitleExportDetailResponse)
async def get_export(
    request: Request, project_id: str, export_id: str
) -> SubtitleExportDetailResponse:
    project = await service(request).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    exp = find_export(project, export_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="export not found")
    return export_to_detail_response(project_id, exp)


@router.get("/{project_id}/exports/{export_id}/download")
async def download_export(request: Request, project_id: str, export_id: str) -> Response:
    project = await service(request).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    exp = find_export(project, export_id)
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

    base_name = safe_filename_base(str(project.name or "subtitles"))
    ascii_base = base_name.encode("ascii", "ignore").decode("ascii") or "subtitles"
    filename = f"{base_name}_{export_id}.{exp.format.value}"
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_base}_{export_id}.{exp.format.value}"; '
            f"filename*=UTF-8''{quote(filename)}"
        ),
    }
    return Response(content=data, media_type=media_type, headers=headers)
