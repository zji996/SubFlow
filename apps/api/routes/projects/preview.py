from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from psycopg.rows import dict_row

from subflow.repositories import GlobalContextRepository

from ._deps import pool, service, to_response
from .schemas import (
    PreviewSegment,
    PreviewSegmentsResponse,
    PreviewSemanticChunk,
    PreviewStats,
    ProjectPreviewResponse,
    VADRegionPreview,
)

router = APIRouter()


@router.get("/{project_id}/preview", response_model=ProjectPreviewResponse)
async def get_project_preview(request: Request, project_id: str) -> ProjectPreviewResponse:
    svc = service(request)
    project = await svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    pool_obj = pool(request)
    global_context_repo = GlobalContextRepository(pool_obj)
    global_context = await global_context_repo.get(project_id) or {}

    async with pool_obj.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT COUNT(*) AS c FROM asr_segments WHERE project_id=%s", (project_id,)
            )
            asr_segment_count = int((await cur.fetchone() or {}).get("c") or 0)

            await cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM asr_segments
                WHERE project_id=%s
                  AND corrected_text IS NOT NULL
                  AND corrected_text <> text
                """,
                (project_id,),
            )
            corrected_count = int((await cur.fetchone() or {}).get("c") or 0)

            await cur.execute(
                "SELECT COUNT(*) AS c FROM semantic_chunks WHERE project_id=%s", (project_id,)
            )
            semantic_chunk_count = int((await cur.fetchone() or {}).get("c") or 0)

            await cur.execute(
                "SELECT COALESCE(MAX(end_time), 0) AS mx FROM asr_segments WHERE project_id=%s",
                (project_id,),
            )
            total_duration_s = float((await cur.fetchone() or {}).get("mx") or 0.0)

            vad_regions: list[VADRegionPreview] = []
            await cur.execute(
                """
                SELECT region_id,
                       MIN(start_time) AS start_time,
                       MAX(end_time) AS end_time,
                       COUNT(*) AS segment_count
                FROM vad_segments
                WHERE project_id=%s AND region_id IS NOT NULL
                GROUP BY region_id
                ORDER BY region_id ASC
                """,
                (project_id,),
            )
            rows = await cur.fetchall()
            if rows:
                vad_regions = [
                    VADRegionPreview(
                        region_id=int(r["region_id"]),
                        start=float(r["start_time"]),
                        end=float(r["end_time"]),
                        segment_count=int(r["segment_count"] or 0),
                    )
                    for r in rows
                ]
            else:
                await cur.execute(
                    """
                    SELECT region_id,
                           MIN(start_time) AS start_time,
                           MAX(end_time) AS end_time,
                           SUM(COALESCE(array_length(segment_ids, 1), 0)) AS segment_count
                    FROM asr_merged_chunks
                    WHERE project_id=%s
                    GROUP BY region_id
                    ORDER BY region_id ASC
                    """,
                    (project_id,),
                )
                rows = await cur.fetchall()
                vad_regions = [
                    VADRegionPreview(
                        region_id=int(r["region_id"]),
                        start=float(r["start_time"]),
                        end=float(r["end_time"]),
                        segment_count=int(r["segment_count"] or 0),
                    )
                    for r in rows
                ]

    stats = PreviewStats(
        vad_region_count=len(vad_regions),
        asr_segment_count=asr_segment_count,
        corrected_count=corrected_count,
        semantic_chunk_count=semantic_chunk_count,
        total_duration_s=total_duration_s,
    )
    return ProjectPreviewResponse(
        project=to_response(project),
        global_context=dict(global_context),
        stats=stats,
        vad_regions=vad_regions,
    )


@router.get("/{project_id}/preview/segments", response_model=PreviewSegmentsResponse)
async def get_project_preview_segments(
    request: Request,
    project_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    region_id: int | None = Query(default=None, ge=0),
) -> PreviewSegmentsResponse:
    pool_obj = pool(request)

    async with pool_obj.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            if region_id is None:
                await cur.execute(
                    "SELECT COUNT(*) AS c FROM asr_segments WHERE project_id=%s", (project_id,)
                )
                total = int((await cur.fetchone() or {}).get("c") or 0)
                await cur.execute(
                    """
                    SELECT segment_index, start_time, end_time, text, corrected_text
                    FROM asr_segments
                    WHERE project_id=%s
                    ORDER BY segment_index ASC
                    LIMIT %s OFFSET %s
                    """,
                    (project_id, int(limit), int(offset)),
                )
            else:
                await cur.execute(
                    "SELECT 1 AS one FROM asr_merged_chunks WHERE project_id=%s LIMIT 1",
                    (project_id,),
                )
                has_merged_chunks = await cur.fetchone() is not None
                if has_merged_chunks:
                    await cur.execute(
                        """
                        WITH seg_ids AS (
                          SELECT DISTINCT UNNEST(segment_ids) AS segment_index
                          FROM asr_merged_chunks
                          WHERE project_id=%s AND region_id=%s
                        )
                        SELECT COUNT(*) AS c
                        FROM asr_segments a
                        JOIN seg_ids s ON s.segment_index = a.segment_index
                        WHERE a.project_id=%s
                        """,
                        (project_id, int(region_id), project_id),
                    )
                    total = int((await cur.fetchone() or {}).get("c") or 0)
                    await cur.execute(
                        """
                        WITH seg_ids AS (
                          SELECT DISTINCT UNNEST(segment_ids) AS segment_index
                          FROM asr_merged_chunks
                          WHERE project_id=%s AND region_id=%s
                        )
                        SELECT a.segment_index, a.start_time, a.end_time, a.text, a.corrected_text
                        FROM asr_segments a
                        JOIN seg_ids s ON s.segment_index = a.segment_index
                        WHERE a.project_id=%s
                        ORDER BY a.segment_index ASC
                        LIMIT %s OFFSET %s
                        """,
                        (project_id, int(region_id), project_id, int(limit), int(offset)),
                    )
                else:
                    await cur.execute(
                        """
                        SELECT COUNT(*) AS c
                        FROM asr_segments a
                        JOIN vad_segments v
                          ON v.project_id=a.project_id AND v.segment_index=a.segment_index
                        WHERE a.project_id=%s AND v.region_id=%s
                        """,
                        (project_id, int(region_id)),
                    )
                    total = int((await cur.fetchone() or {}).get("c") or 0)
                    await cur.execute(
                        """
                        SELECT a.segment_index, a.start_time, a.end_time, a.text, a.corrected_text
                        FROM asr_segments a
                        JOIN vad_segments v
                          ON v.project_id=a.project_id AND v.segment_index=a.segment_index
                        WHERE a.project_id=%s AND v.region_id=%s
                        ORDER BY a.segment_index ASC
                        LIMIT %s OFFSET %s
                        """,
                        (project_id, int(region_id), int(limit), int(offset)),
                    )
            seg_rows = await cur.fetchall()

            seg_ids = [int(r["segment_index"]) for r in seg_rows]
            semantic_rows: list[dict[str, object]] = []
            translation_rows: list[dict[str, object]] = []
            if seg_ids:
                await cur.execute(
                    """
                    SELECT id, chunk_index, text, translation, asr_segment_ids
                    FROM semantic_chunks
                    WHERE project_id=%s AND asr_segment_ids && %s::integer[]
                    ORDER BY chunk_index ASC
                    """,
                    (project_id, seg_ids),
                )
                semantic_rows = await cur.fetchall()
                semantic_ids = [int(r["id"]) for r in semantic_rows]
                if semantic_ids:
                    await cur.execute(
                        """
                        SELECT semantic_chunk_id, chunk_order, text, segment_ids
                        FROM translation_chunks
                        WHERE semantic_chunk_id = ANY(%s)
                        ORDER BY semantic_chunk_id ASC, chunk_order ASC
                        """,
                        (semantic_ids,),
                    )
                    translation_rows = await cur.fetchall()

    seg_to_semantic: dict[int, dict[str, object]] = {}
    for r in semantic_rows:
        chunk_index = int(r.get("chunk_index") or 0)
        item = {
            "id": chunk_index,
            "text": str(r.get("text") or ""),
            "translation": str(r.get("translation") or ""),
        }
        for sid in list(r.get("asr_segment_ids") or []):
            try:
                seg_to_semantic[int(sid)] = item
            except (TypeError, ValueError):
                continue

    seg_to_translation_texts: dict[int, list[str]] = {}
    for tr in translation_rows:
        text = str(tr.get("text") or "").strip()
        if not text:
            continue
        for sid in list(tr.get("segment_ids") or []):
            try:
                seg_to_translation_texts.setdefault(int(sid), []).append(text)
            except (TypeError, ValueError):
                continue

    segments: list[PreviewSegment] = []
    for r in seg_rows:
        sid = int(r["segment_index"])
        semantic = seg_to_semantic.get(sid)
        semantic_obj: PreviewSemanticChunk | None = None
        if semantic is not None:
            semantic_obj = PreviewSemanticChunk(
                id=int(semantic["id"]),
                text=str(semantic["text"]),
                translation=str(semantic["translation"]),
                translation_chunk_text=" ".join(seg_to_translation_texts.get(sid, [])),
            )
        corrected_text = r.get("corrected_text")
        segments.append(
            PreviewSegment(
                id=sid,
                start=float(r["start_time"]),
                end=float(r["end_time"]),
                text=str(r.get("text") or ""),
                corrected_text=str(corrected_text) if corrected_text is not None else None,
                semantic_chunk=semantic_obj,
            )
        )

    return PreviewSegmentsResponse(total=int(total), segments=segments)
