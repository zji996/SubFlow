from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from subflow.models.segment import ASRMergedChunk
from subflow.repositories.base import BaseRepository


class ASRMergedChunkRepository(BaseRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        super().__init__(pool)

    async def bulk_upsert(self, project_id: str, chunks: list[ASRMergedChunk]) -> None:
        rows = [
            (
                str(project_id),
                int(ch.region_id),
                int(ch.chunk_id),
                float(ch.start),
                float(ch.end),
                [int(x) for x in list(ch.segment_ids or [])],
                str(ch.text or ""),
            )
            for ch in list(chunks or [])
        ]
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                if rows:
                    await cur.executemany(
                        """
                        INSERT INTO asr_merged_chunks (
                          project_id, region_id, chunk_id, start_time, end_time, segment_ids, text
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (project_id, region_id, chunk_id) DO UPDATE
                        SET start_time=EXCLUDED.start_time,
                            end_time=EXCLUDED.end_time,
                            segment_ids=EXCLUDED.segment_ids,
                            text=EXCLUDED.text
                        """,
                        rows,
                    )
            await conn.commit()

    async def get_by_project(self, project_id: str) -> list[ASRMergedChunk]:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT region_id, chunk_id, start_time, end_time, segment_ids, text
                    FROM asr_merged_chunks
                    WHERE project_id=%s
                    ORDER BY region_id ASC, chunk_id ASC
                    """,
                    (str(project_id),),
                )
                rows = await cur.fetchall()
        return [
            ASRMergedChunk(
                region_id=int(r["region_id"]),
                chunk_id=int(r["chunk_id"]),
                start=float(r["start_time"]),
                end=float(r["end_time"]),
                segment_ids=[int(x) for x in list(r.get("segment_ids") or [])],
                text=str(r.get("text") or ""),
            )
            for r in rows
        ]

    async def delete_by_project(self, project_id: str) -> None:
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM asr_merged_chunks WHERE project_id=%s", (str(project_id),))
            await conn.commit()

