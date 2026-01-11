from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from subflow.models.segment import ASRSegment
from subflow.repositories.base import BaseRepository


class ASRSegmentRepository(BaseRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        super().__init__(pool)

    async def bulk_insert(self, project_id: str, segments: list[ASRSegment]) -> None:
        rows = [
            (
                project_id,
                int(seg.id),
                float(seg.start),
                float(seg.end),
                str(seg.text or ""),
                None,
                seg.language,
                None,
            )
            for seg in list(segments or [])
        ]
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                if rows:
                    await cur.executemany(
                        """
                        INSERT INTO asr_segments (
                          project_id, segment_index, start_time, end_time, text,
                          corrected_text, language, confidence
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        rows,
                    )
            await conn.commit()

    async def get_by_project(self, project_id: str, *, use_corrected: bool = False) -> list[ASRSegment]:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT segment_index, start_time, end_time, text, corrected_text, language
                    FROM asr_segments
                    WHERE project_id=%s
                    ORDER BY segment_index ASC
                    """,
                    (project_id,),
                )
                rows = await cur.fetchall()
        out: list[ASRSegment] = []
        for r in rows:
            text = str(r["text"] or "")
            if use_corrected and r.get("corrected_text") is not None:
                text = str(r["corrected_text"] or "")
            out.append(
                ASRSegment(
                    id=int(r["segment_index"]),
                    start=float(r["start_time"]),
                    end=float(r["end_time"]),
                    text=text,
                    language=r.get("language") if r.get("language") is not None else None,
                )
            )
        return out

    async def get_corrected_map(self, project_id: str) -> dict[int, str]:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT segment_index, corrected_text
                    FROM asr_segments
                    WHERE project_id=%s AND corrected_text IS NOT NULL
                    ORDER BY segment_index ASC
                    """,
                    (project_id,),
                )
                rows = await cur.fetchall()
        return {int(r["segment_index"]): str(r["corrected_text"] or "") for r in rows}

    async def update_corrected_texts(self, project_id: str, corrections: dict[int, str]) -> None:
        rows = [(str(text or ""), project_id, int(i)) for i, text in dict(corrections or {}).items()]
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                if rows:
                    await cur.executemany(
                        """
                        UPDATE asr_segments
                        SET corrected_text=%s
                        WHERE project_id=%s AND segment_index=%s
                        """,
                        rows,
                    )
            await conn.commit()

    async def get_by_time_range(self, project_id: str, start: float, end: float) -> list[ASRSegment]:
        start_f = float(start)
        end_f = float(end)
        if end_f < start_f:
            start_f, end_f = end_f, start_f
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT segment_index, start_time, end_time, text, corrected_text, language
                    FROM asr_segments
                    WHERE project_id=%s
                      AND end_time >= %s
                      AND start_time <= %s
                    ORDER BY start_time ASC, segment_index ASC
                    """,
                    (project_id, start_f, end_f),
                )
                rows = await cur.fetchall()
        return [
            ASRSegment(
                id=int(r["segment_index"]),
                start=float(r["start_time"]),
                end=float(r["end_time"]),
                text=str(r["text"] or ""),
                language=r.get("language") if r.get("language") is not None else None,
            )
            for r in rows
        ]

    async def delete_by_project(self, project_id: str) -> None:
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM asr_segments WHERE project_id=%s", (project_id,))
            await conn.commit()

