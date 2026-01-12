from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from subflow.config import Settings
from subflow.export import SubtitleExporter
from subflow.export.formatters.base import SubtitleFormatter, selected_lines
from subflow.models.segment import ASRCorrectedSegment, SemanticChunk
from subflow.models.serializers import serialize_asr_segments, serialize_semantic_chunks
from subflow.models.subtitle_types import (
    AssStyleConfig,
    SubtitleContent,
    SubtitleExportConfig,
    SubtitleFormat,
    TranslationStyle,
)

from ._deps import load_subtitle_materials, pool, safe_filename_base, service
from .schemas import (
    SubtitleEditComputedEntry,
    SubtitleEditDataResponse,
    SubtitlePreviewEntry,
    SubtitlePreviewResponse,
)

router = APIRouter()


@router.get("/{project_id}/subtitles/preview", response_model=SubtitlePreviewResponse)
async def preview_subtitles(
    request: Request,
    project_id: str,
    format: str = Query(default="srt", pattern="^(srt|vtt|ass|json)$"),
    content: str = Query(default="both", pattern="^(both|primary_only|secondary_only)$"),
    primary_position: str = Query(default="top", pattern="^(top|bottom)$"),
) -> SubtitlePreviewResponse:
    project = await service(request).get_project(project_id)
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

    chunks, asr_segments, corrected = await load_subtitle_materials(pool(request), project_id)
    if not asr_segments:
        raise HTTPException(status_code=404, detail="asr segments not found")

    config = SubtitleExportConfig(
        format=fmt, content=content_mode, primary_position=primary_position
    )
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


@router.get("/{project_id}/subtitles/edit-data", response_model=SubtitleEditDataResponse)
async def get_subtitle_edit_data(request: Request, project_id: str) -> SubtitleEditDataResponse:
    project = await service(request).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    chunks, asr_segments, corrected = await load_subtitle_materials(pool(request), project_id)
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
            seg_id = int(ch.segment_id)
            per_chunk_translation.setdefault(seg_id, str(ch.text or "").strip())

    ordered_segments = sorted(asr_segments, key=lambda s: (float(s.start), float(s.end), int(s.id)))

    computed: list[SubtitleEditComputedEntry] = []
    for seg in ordered_segments:
        corrected_seg = corrected_by_asr_id.get(int(seg.id))
        secondary = (str(corrected_seg.text).strip() if corrected_seg is not None else "") or str(
            seg.text or ""
        ).strip()
        chunk_for_seg = chunk_by_segment_id.get(int(seg.id))
        semantic_chunk_id = int(chunk_for_seg.id) if chunk_for_seg is not None else None
        computed.append(
            SubtitleEditComputedEntry(
                segment_id=int(seg.id),
                start=float(seg.start),
                end=float(seg.end),
                secondary=secondary,
                primary_per_chunk=str(per_chunk_translation.get(int(seg.id), "") or "").strip(),
                primary_full=str(
                    (chunk_for_seg.translation if chunk_for_seg is not None else "") or ""
                ).strip(),
                semantic_chunk_id=semantic_chunk_id,
            )
        )

    return SubtitleEditDataResponse(
        asr_segments=serialize_asr_segments(ordered_segments),
        asr_corrected_segments={
            int(asr_id): {
                "id": int(seg.id),
                "asr_segment_id": int(seg.asr_segment_id),
                "text": seg.text,
            }
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
    translation_style: str = Query(default="per_chunk"),
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
    project = await service(request).get_project(project_id)
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
        trans_style = TranslationStyle.parse(translation_style)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    chunks, asr_segments, corrected = await load_subtitle_materials(pool(request), project_id)
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
            secondary_outline_color=secondary_outline_color
            or default_style.secondary_outline_color,
            secondary_outline_width=secondary_outline_width
            or default_style.secondary_outline_width,
            position=position or default_style.position,
            margin=margin or default_style.margin,
        )

    config = SubtitleExportConfig(
        format=fmt,
        content=content_mode,
        primary_position=primary_position,
        translation_style=trans_style,
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

    base_name = safe_filename_base(str(project.name or "subtitles"))
    ascii_base = base_name.encode("ascii", "ignore").decode("ascii") or "subtitles"
    filename = f"{base_name}.{fmt.value}"
    headers = {
        "Content-Disposition": (
            f"attachment; filename=\"{ascii_base}.{fmt.value}\"; filename*=UTF-8''{quote(filename)}"
        ),
    }
    return Response(content=subtitle_text, media_type=media_type, headers=headers)
