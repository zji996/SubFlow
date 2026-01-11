from __future__ import annotations

import json
from datetime import datetime, timezone

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from subflow.models.project import Project, ProjectStatus
from subflow.repositories.base import BaseRepository


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


class ProjectRepository(BaseRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        super().__init__(pool)

    @staticmethod
    def _from_row(row: dict[str, object]) -> Project:
        return Project(
            id=str(row["id"]),
            name=str(row["name"]),
            media_url=str(row["media_url"]),
            media_files=_as_dict(row.get("media_files")),
            source_language=row.get("source_language") if row.get("source_language") is not None else None,
            target_language=str(row.get("target_language") or "zh"),
            auto_workflow=bool(row.get("auto_workflow", True)),
            status=ProjectStatus(str(row.get("status") or ProjectStatus.PENDING.value)),
            current_stage=int(row.get("current_stage") or 0),
            artifacts={},
            stage_runs=[],
            exports=[],
            created_at=row.get("created_at") if isinstance(row.get("created_at"), datetime) else _utcnow(),
            updated_at=row.get("updated_at") if isinstance(row.get("updated_at"), datetime) else _utcnow(),
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

    async def delete(self, project_id: str) -> bool:
        async with self.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM projects WHERE id=%s", (project_id,))
                removed = cur.rowcount
            await conn.commit()
        return bool(removed)

    async def list(self, limit: int = 100, offset: int = 0) -> list[Project]:
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
