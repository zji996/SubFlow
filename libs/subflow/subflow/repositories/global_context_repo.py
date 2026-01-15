from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from subflow.repositories.base import BaseRepository

GlobalContext = dict[str, Any]


class GlobalContextRepository(BaseRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        super().__init__(pool)

    async def save(self, project_id: str, context: GlobalContext) -> None:
        ctx = dict(context or {})
        topic = ctx.get("topic")
        domain = ctx.get("domain")
        style = ctx.get("style")
        glossary = ctx.get("glossary")
        translation_notes = ctx.get("translation_notes")

        if not isinstance(glossary, dict):
            glossary = {}
        notes: list[str] = []
        if isinstance(translation_notes, list):
            notes = [str(x) for x in translation_notes]

        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO global_contexts (
                      project_id, topic, domain, style, glossary, translation_notes
                    )
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (project_id) DO UPDATE SET
                      topic=EXCLUDED.topic,
                      domain=EXCLUDED.domain,
                      style=EXCLUDED.style,
                      glossary=EXCLUDED.glossary,
                      translation_notes=EXCLUDED.translation_notes
                    """,
                    (
                        project_id,
                        str(topic) if topic is not None else None,
                        str(domain) if domain is not None else None,
                        str(style) if style is not None else None,
                        Jsonb(glossary),
                        notes,
                    ),
                )
            await conn.commit()

    async def get(self, project_id: str) -> GlobalContext | None:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT project_id, topic, domain, style, glossary, translation_notes
                    FROM global_contexts
                    WHERE project_id=%s
                    """,
                    (project_id,),
                )
                row = await cur.fetchone()
        if row is None:
            return None
        glossary = row.get("glossary")
        if not isinstance(glossary, dict):
            glossary = {}
        notes = row.get("translation_notes")
        if not isinstance(notes, list):
            notes = []
        return {
            "topic": row.get("topic"),
            "domain": row.get("domain"),
            "style": row.get("style"),
            "glossary": dict(glossary),
            "translation_notes": [str(x) for x in list(notes or [])],
        }

    async def delete(self, project_id: str) -> None:
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM global_contexts WHERE project_id=%s", (project_id,))
            await conn.commit()
