from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from subflow.models.project import StageName, StageRun, StageRunStatus
from subflow.repositories.base import BaseRepository


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


class StageRunRepository(BaseRepository):
    def __init__(self, pool: AsyncConnectionPool) -> None:
        super().__init__(pool)

    @staticmethod
    def _from_row(row: dict[str, object]) -> StageRun:
        metadata = _as_dict(row.get("metadata"))
        metrics = _as_dict(metadata.get("metrics"))
        started_at = row.get("started_at")
        completed_at = row.get("completed_at")
        return StageRun(
            stage=StageName(str(row["stage"])),
            status=StageRunStatus(str(row.get("status") or StageRunStatus.PENDING.value)),
            started_at=started_at if isinstance(started_at, datetime) else None,
            completed_at=completed_at if isinstance(completed_at, datetime) else None,
            duration_ms=int(metadata["duration_ms"])
            if isinstance(metadata.get("duration_ms"), int)
            else None,
            progress=int(metadata["progress"])
            if isinstance(metadata.get("progress"), int)
            else None,
            progress_message=str(metadata.get("progress_message") or "") or None,
            metrics=metrics,
            error_code=str(metadata.get("error_code") or "") or None,
            error_message=str(row.get("error_message") or "") or None,
            input_artifacts=_as_dict(metadata.get("input_artifacts")),
            output_artifacts=_as_dict(metadata.get("output_artifacts")),
        )

    async def create_or_update(
        self,
        project_id: str,
        stage: str,
        status: str,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StageRun:
        meta = dict(metadata or {})
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO stage_runs (
                      project_id, stage, status, started_at, completed_at, error_message, metadata
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (project_id, stage) DO UPDATE SET
                      status=EXCLUDED.status,
                      started_at=COALESCE(EXCLUDED.started_at, stage_runs.started_at),
                      completed_at=EXCLUDED.completed_at,
                      error_message=EXCLUDED.error_message,
                      metadata=EXCLUDED.metadata
                    RETURNING project_id, stage, status, started_at, completed_at, error_message, metadata
                    """,
                    (
                        project_id,
                        str(stage),
                        str(status),
                        started_at,
                        completed_at,
                        error_message,
                        Jsonb(meta),
                    ),
                )
                row = await cur.fetchone()
            await conn.commit()
        if row is None:
            raise RuntimeError("stage_run upsert returned no row")
        return self._from_row(row)

    async def get(self, project_id: str, stage: str) -> StageRun | None:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT project_id, stage, status, started_at, completed_at, error_message, metadata
                    FROM stage_runs
                    WHERE project_id=%s AND stage=%s
                    """,
                    (project_id, str(stage)),
                )
                row = await cur.fetchone()
        return self._from_row(row) if row is not None else None

    async def list_by_project(self, project_id: str) -> list[StageRun]:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT project_id, stage, status, started_at, completed_at, error_message, metadata
                    FROM stage_runs
                    WHERE project_id=%s
                    ORDER BY stage
                    """,
                    (project_id,),
                )
                rows = await cur.fetchall()
        return [self._from_row(r) for r in rows]

    async def mark_running(self, project_id: str, stage: str) -> StageRun:
        now = _utcnow()
        return await self.create_or_update(
            project_id,
            stage,
            StageRunStatus.RUNNING.value,
            started_at=now,
            completed_at=None,
            error_message=None,
            metadata={"progress": 0, "progress_message": "running"},
        )

    async def mark_completed(
        self,
        project_id: str,
        stage: str,
        metadata: dict[str, Any] | None = None,
    ) -> StageRun:
        now = _utcnow()
        meta = dict(metadata or {})
        return await self.create_or_update(
            project_id,
            stage,
            StageRunStatus.COMPLETED.value,
            completed_at=now,
            error_message=None,
            metadata=meta,
        )

    async def mark_failed(
        self,
        project_id: str,
        stage: str,
        error_code: str,
        error_message: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> StageRun:
        now = _utcnow()
        meta = dict(metadata or {})
        meta["error_code"] = str(error_code)
        return await self.create_or_update(
            project_id,
            stage,
            StageRunStatus.FAILED.value,
            completed_at=now,
            error_message=str(error_message or ""),
            metadata=meta,
        )

    async def reset_to_pending(self, project_id: str, stage: str) -> StageRun:
        """Reset stage run to pending, clearing timestamps, errors, and metadata."""
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO stage_runs (
                      project_id, stage, status, started_at, completed_at, error_message, metadata
                    )
                    VALUES (%s,%s,%s,NULL,NULL,NULL,'{}'::jsonb)
                    ON CONFLICT (project_id, stage) DO UPDATE SET
                      status=EXCLUDED.status,
                      started_at=NULL,
                      completed_at=NULL,
                      error_message=NULL,
                      metadata='{}'::jsonb
                    RETURNING project_id, stage, status, started_at, completed_at, error_message, metadata
                    """,
                    (project_id, str(stage), StageRunStatus.PENDING.value),
                )
                row = await cur.fetchone()
            await conn.commit()
        if row is None:
            raise RuntimeError("stage_run reset returned no row")
        return self._from_row(row)

    async def set_progress(
        self,
        project_id: str,
        stage: str,
        *,
        progress: int,
        message: str,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        async with self.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT metadata FROM stage_runs WHERE project_id=%s AND stage=%s",
                    (project_id, str(stage)),
                )
                row = await cur.fetchone()
                current = _as_dict(row.get("metadata") if row else None)
                current["progress"] = max(0, min(100, int(progress)))
                current["progress_message"] = str(message or "").strip() or "running"
                if metrics:
                    current_metrics = _as_dict(current.get("metrics"))
                    current_metrics.update(dict(metrics))
                    current["metrics"] = current_metrics
                await cur.execute(
                    """
                    UPDATE stage_runs
                    SET metadata=%s
                    WHERE project_id=%s AND stage=%s
                    """,
                    (Jsonb(current), project_id, str(stage)),
                )
            await conn.commit()
