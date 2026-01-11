from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from subflow.models.segment import SemanticChunk, TranslationChunk
from subflow.repositories.base import BaseRepository


class SemanticChunkRepository(BaseRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        super().__init__(pool)

    async def bulk_insert(self, project_id: str, chunks: list[SemanticChunk]) -> list[int]:
        new_ids: list[int] = []
        async with self.connection() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    for chunk in list(chunks or []):
                        await cur.execute(
                            """
                            INSERT INTO semantic_chunks (
                              project_id, chunk_index, text, translation, asr_segment_ids
                            )
                            VALUES (%s,%s,%s,%s,%s)
                            RETURNING id
                            """,
                            (
                                project_id,
                                int(chunk.id),
                                str(chunk.text or ""),
                                str(chunk.translation or "") if chunk.translation is not None else None,
                                [int(x) for x in list(chunk.asr_segment_ids or [])],
                            ),
                        )
                        row = await cur.fetchone()
                        if row is None or row.get("id") is None:
                            raise RuntimeError("semantic_chunks insert returned no id")
                        semantic_chunk_id = int(row["id"])
                        new_ids.append(semantic_chunk_id)

                        trows = [
                            (
                                semantic_chunk_id,
                                int(i),
                                str(ch.text or ""),
                                [int(ch.segment_id)],
                            )
                            for i, ch in enumerate(list(chunk.translation_chunks or []))
                        ]
                        if trows:
                            await cur.executemany(
                                """
                                INSERT INTO translation_chunks (
                                  semantic_chunk_id, chunk_order, text, segment_ids
                                )
                                VALUES (%s,%s,%s,%s)
                                """,
                                trows,
                            )
        return new_ids

    async def get_by_project(self, project_id: str) -> list[SemanticChunk]:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT id, chunk_index, text, translation, asr_segment_ids
                    FROM semantic_chunks
                    WHERE project_id=%s
                    ORDER BY chunk_index ASC
                    """,
                    (project_id,),
                )
                chunk_rows = await cur.fetchall()
                semantic_ids = [int(r["id"]) for r in chunk_rows]
                translation_rows: list[dict[str, object]] = []
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

        translations_by_semantic_id: dict[int, list[TranslationChunk]] = {}
        for tr in translation_rows:
            sid = int(tr["semantic_chunk_id"])
            text = str(tr.get("text") or "")
            raw_ids = tr.get("segment_ids") or []
            if not isinstance(raw_ids, list):
                raw_ids = []
            for seg_id in [int(x) for x in list(raw_ids or [])]:
                translations_by_semantic_id.setdefault(sid, []).append(
                    TranslationChunk(text=text, segment_id=int(seg_id))
                )

        out: list[SemanticChunk] = []
        for r in chunk_rows:
            sid = int(r["id"])
            out.append(
                SemanticChunk(
                    id=int(r.get("chunk_index") or 0),
                    text=str(r.get("text") or ""),
                    translation=str(r.get("translation") or ""),
                    asr_segment_ids=[int(x) for x in list(r.get("asr_segment_ids") or [])],
                    translation_chunks=list(translations_by_semantic_id.get(sid, [])),
                )
            )
        return out

    async def delete_by_project(self, project_id: str) -> None:
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM semantic_chunks WHERE project_id=%s", (project_id,))
            await conn.commit()
