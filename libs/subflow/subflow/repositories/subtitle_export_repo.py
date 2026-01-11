from __future__ import annotations

import json
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from subflow.models.subtitle_export import SubtitleExport, SubtitleExportSource
from subflow.models.subtitle_types import SubtitleContent, SubtitleFormat
from subflow.repositories.base import BaseRepository


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


class SubtitleExportRepository(BaseRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        super().__init__(pool)

    @staticmethod
    def _from_row(row: dict[str, object]) -> SubtitleExport:
        fmt = SubtitleFormat(str(row.get("format") or SubtitleFormat.SRT.value))
        content_mode = SubtitleContent(str(row.get("content_mode") or SubtitleContent.BOTH.value))
        source = SubtitleExportSource(str(row.get("source") or SubtitleExportSource.AUTO.value))

        config_obj = _as_dict(row.get("config_json"))
        config_json = json.dumps(config_obj, ensure_ascii=False)

        export_id = str(row["id"])
        storage_stage = "exports"
        storage_name = f"{export_id}.{fmt.value}"
        entries_name = None
        if config_obj.get("has_entries"):
            entries_name = f"{export_id}.entries.json"

        created_at = row.get("created_at")
        from datetime import datetime, timezone

        if not isinstance(created_at, datetime):
            created_at = datetime.now(tz=timezone.utc)

        return SubtitleExport(
            id=export_id,
            project_id=str(row["project_id"]),
            created_at=created_at,
            format=fmt,
            content_mode=content_mode,
            config_json=config_json,
            storage_stage=storage_stage,
            storage_name=storage_name,
            storage_key=str(row.get("storage_key") or ""),
            source=source,
            entries_name=entries_name,
            entries_key=None,
        )

    async def create(self, export: SubtitleExport) -> SubtitleExport:
        try:
            config_obj = json.loads(export.config_json or "{}")
        except json.JSONDecodeError:
            config_obj = {}
        if not isinstance(config_obj, dict):
            config_obj = {}
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO subtitle_exports (
                      id, project_id, created_at, format, content_mode, source, config_json, storage_key
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id, project_id, created_at, format, content_mode, source, config_json, storage_key
                    """,
                    (
                        export.id,
                        export.project_id,
                        export.created_at,
                        export.format.value,
                        export.content_mode.value,
                        export.source.value,
                        Jsonb(config_obj),
                        export.storage_key,
                    ),
                )
                row = await cur.fetchone()
            await conn.commit()
        if row is None:
            raise RuntimeError("subtitle_exports insert returned no row")
        return self._from_row(row)

    async def get(self, export_id: str) -> SubtitleExport | None:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT id, project_id, created_at, format, content_mode, source, config_json, storage_key
                    FROM subtitle_exports
                    WHERE id=%s
                    """,
                    (export_id,),
                )
                row = await cur.fetchone()
        return self._from_row(row) if row is not None else None

    async def list_by_project(self, project_id: str) -> list[SubtitleExport]:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT id, project_id, created_at, format, content_mode, source, config_json, storage_key
                    FROM subtitle_exports
                    WHERE project_id=%s
                    ORDER BY created_at DESC
                    """,
                    (project_id,),
                )
                rows = await cur.fetchall()
        return [self._from_row(r) for r in rows]

