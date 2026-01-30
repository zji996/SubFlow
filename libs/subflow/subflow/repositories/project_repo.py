from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
import builtins
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from subflow.models.project import Project, ProjectStatus
from subflow.repositories.base import BaseRepository
from subflow.storage.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _as_dict(value: object) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            return {}
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _as_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            return int(default)
    if isinstance(value, str):
        try:
            return int(value.strip() or default)
        except ValueError:
            return int(default)
    return int(default)


class ProjectRepository(BaseRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        super().__init__(pool)

    @staticmethod
    def _from_row(row: dict[str, object]) -> Project:
        raw_source_language = row.get("source_language")
        source_language = str(raw_source_language) if raw_source_language is not None else None
        raw_created_at = row.get("created_at")
        created_at = raw_created_at if isinstance(raw_created_at, datetime) else _utcnow()
        raw_updated_at = row.get("updated_at")
        updated_at = raw_updated_at if isinstance(raw_updated_at, datetime) else _utcnow()
        return Project(
            id=str(row["id"]),
            name=str(row["name"]),
            media_url=str(row["media_url"]),
            media_files=_as_dict(row.get("media_files")),
            source_language=source_language,
            target_language=str(row.get("target_language") or "zh"),
            auto_workflow=bool(row.get("auto_workflow", True)),
            status=ProjectStatus(str(row.get("status") or ProjectStatus.PENDING.value)),
            current_stage=_as_int(row.get("current_stage"), default=0),
            artifacts={},
            stage_runs=[],
            exports=[],
            created_at=created_at,
            updated_at=updated_at,
        )

    async def create(self, project: Project) -> Project:
        now = _utcnow()
        created_at = project.created_at or now
        updated_at = project.updated_at or now
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO projects (
                      id, name, media_url, media_files, source_language, target_language,
                      auto_workflow, status, current_stage, error_message,
                      created_at, updated_at
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        project.id,
                        project.name,
                        project.media_url,
                        Jsonb(dict(project.media_files or {})),
                        project.source_language,
                        project.target_language,
                        bool(project.auto_workflow),
                        project.status.value,
                        int(project.current_stage),
                        None,
                        created_at,
                        updated_at,
                    ),
                )
            await conn.commit()
        project.created_at = created_at
        project.updated_at = updated_at
        return project

    async def get(self, project_id: str) -> Project | None:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT id, name, media_url, media_files, source_language, target_language,
                           auto_workflow, status, current_stage, error_message,
                           created_at, updated_at
                    FROM projects
                    WHERE id = %s
                    """,
                    (project_id,),
                )
                row = await cur.fetchone()
        if row is None:
            return None
        return self._from_row(row)

    async def update(self, project: Project) -> Project:
        project.updated_at = _utcnow()
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE projects
                    SET name=%s,
                        media_url=%s,
                        media_files=%s,
                        source_language=%s,
                        target_language=%s,
                        auto_workflow=%s,
                        status=%s,
                        current_stage=%s,
                        updated_at=%s
                    WHERE id=%s
                    """,
                    (
                        project.name,
                        project.media_url,
                        Jsonb(dict(project.media_files or {})),
                        project.source_language,
                        project.target_language,
                        bool(project.auto_workflow),
                        project.status.value,
                        int(project.current_stage),
                        project.updated_at,
                        project.id,
                    ),
                )
            await conn.commit()
        return project

    async def _delete_related_tables(self, cur: psycopg.AsyncCursor[Any], project_id: str) -> None:
        # These tables are expected to exist in the primary schema. Some deployments may have
        # partial schemas, so we guard with `to_regclass`.
        tables = [
            "subtitle_exports",
            "translation_chunks",
            "semantic_chunks",
            "global_contexts",
            "asr_merged_chunks",
            "asr_segments",
            "vad_segments",
            "stage_runs",
        ]
        for table in tables:
            await cur.execute("SELECT to_regclass(%s)", (table,))
            exists = await cur.fetchone()
            if not exists or exists[0] is None:
                continue
            if table == "translation_chunks":
                # translation_chunks is keyed by semantic_chunk_id; removing semantic_chunks is sufficient.
                continue
            await cur.execute(f"DELETE FROM {table} WHERE project_id=%s", (project_id,))

    async def delete(self, project_id: str, *, store: ArtifactStore | None = None) -> bool:
        """Delete project and all associated data.

        Args:
            project_id: Project ID to delete.
            store: Optional artifact store to clean up S3/local files.
        """
        removed = 0
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1 FROM projects WHERE id=%s", (project_id,))
                if await cur.fetchone() is None:
                    return False

                await self._delete_related_tables(cur, project_id)
                await cur.execute("DELETE FROM projects WHERE id=%s", (project_id,))
                removed = int(cur.rowcount or 0)
            await conn.commit()

        if removed and store is not None:
            try:
                deleted = await store.delete_project(project_id)
                logger.info(
                    "project artifacts deleted (project_id=%s, objects=%d)",
                    project_id,
                    deleted,
                )
            except Exception as exc:
                logger.warning(
                    "project artifacts delete failed (project_id=%s): %s",
                    project_id,
                    exc,
                )

        return bool(removed)

    async def list_all_ids(self) -> builtins.list[str]:
        """Return all project IDs in the database."""
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM projects")
                rows = await cur.fetchall()
        return [str(row[0]) for row in rows]

    async def list(self, limit: int = 100, offset: int = 0) -> builtins.list[Project]:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT id, name, media_url, media_files, source_language, target_language,
                           auto_workflow, status, current_stage, error_message,
                           created_at, updated_at
                    FROM projects
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (int(limit), int(offset)),
                )
                rows = await cur.fetchall()
        return [self._from_row(r) for r in rows]

    async def find_stale_processing(
        self, *, max_age_minutes: int = 10, limit: int = 200
    ) -> builtins.list[Project]:
        """Find projects stuck in processing with old updated_at timestamps."""
        max_age_minutes = max(1, int(max_age_minutes))
        limit = max(1, min(1000, int(limit)))
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT id, name, media_url, media_files, source_language, target_language,
                           auto_workflow, status, current_stage, error_message,
                           created_at, updated_at
                    FROM projects
                    WHERE status = %s
                      AND updated_at < (NOW() - (%s * INTERVAL '1 minute'))
                    ORDER BY updated_at ASC
                    LIMIT %s
                    """,
                    (ProjectStatus.PROCESSING.value, max_age_minutes, limit),
                )
                rows = await cur.fetchall()
        return [self._from_row(r) for r in rows]

    async def update_media_files(self, project_id: str, media_files: dict[str, object]) -> None:
        now = _utcnow()
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE projects
                    SET media_files=%s, updated_at=%s
                    WHERE id=%s
                    """,
                    (Jsonb(dict(media_files or {})), now, str(project_id)),
                )
            await conn.commit()

    async def update_status(
        self,
        project_id: str,
        status: str,
        current_stage: int | None = None,
        *,
        error_message: str | None = None,
    ) -> None:
        now = _utcnow()
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                if current_stage is None:
                    await cur.execute(
                        """
                        UPDATE projects
                        SET status=%s, error_message=%s, updated_at=%s
                        WHERE id=%s
                        """,
                        (str(status), error_message, now, project_id),
                    )
                else:
                    await cur.execute(
                        """
                        UPDATE projects
                        SET status=%s, current_stage=%s, error_message=%s, updated_at=%s
                        WHERE id=%s
                        """,
                        (str(status), int(current_stage), error_message, now, project_id),
                    )
            await conn.commit()
