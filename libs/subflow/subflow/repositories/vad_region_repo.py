from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from subflow.models.segment import VADSegment
from subflow.repositories.base import BaseRepository


class VADRegionRepository(BaseRepository):
    """Persist VAD regions into PostgreSQL.

    Note: regions are stored in the `vad_segments` table for historical reasons.
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        super().__init__(pool)

    async def bulk_insert(self, project_id: str, regions: list[VADSegment]) -> None:
        rows = [
            (
                project_id,
                int(i),
                float(region.start),
                float(region.end),
                int(region.region_id) if region.region_id is not None else None,
            )
            for i, region in enumerate(list(regions or []))
        ]
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                if rows:
                    await cur.executemany(
                        """
                        INSERT INTO vad_segments (project_id, segment_index, start_time, end_time, region_id)
                        VALUES (%s,%s,%s,%s,%s)
                        """,
                        rows,
                    )
            await conn.commit()

    async def get_by_project(self, project_id: str) -> list[VADSegment]:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT segment_index, start_time, end_time, region_id
                    FROM vad_segments
                    WHERE project_id=%s
                    ORDER BY segment_index ASC
                    """,
                    (project_id,),
                )
                rows = await cur.fetchall()
        return [
            VADSegment(
                start=float(r["start_time"]),
                end=float(r["end_time"]),
                region_id=int(r["region_id"]) if r.get("region_id") is not None else None,
            )
            for r in rows
        ]

    async def delete_by_project(self, project_id: str) -> None:
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM vad_segments WHERE project_id=%s", (project_id,))
            await conn.commit()
