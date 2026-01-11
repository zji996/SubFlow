"""Project CRUD and queue operations backed by PostgreSQL + Redis queue."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from redis.asyncio import Redis
from psycopg_pool import AsyncConnectionPool

from subflow.config import Settings
from subflow.models.project import Project, ProjectStatus, StageName
from subflow.repositories import (
    ProjectRepository,
    StageRunRepository,
    SubtitleExportRepository,
)
from subflow.services import BlobStore

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, redis: Redis, settings: Settings, pool: AsyncConnectionPool):
        self.redis = redis
        self.settings = settings
        self.project_repo = ProjectRepository(pool)
        self.stage_run_repo = StageRunRepository(pool)
        self.subtitle_export_repo = SubtitleExportRepository(pool)

    @staticmethod
    def _queue_key() -> str:
        return "subflow:projects:queue"

    async def _hydrate_project(self, project: Project) -> Project:
        project.stage_runs = await self.stage_run_repo.list_by_project(project.id)
        stage_order = {
            StageName.AUDIO_PREPROCESS: 1,
            StageName.VAD: 2,
            StageName.ASR: 3,
            StageName.LLM_ASR_CORRECTION: 4,
            StageName.LLM: 5,
        }
        project.stage_runs.sort(key=lambda sr: stage_order.get(sr.stage, 999))
        project.exports = await self.subtitle_export_repo.list_by_project(project.id)
        project.artifacts = {}
        return project

    async def create_project(
        self,
        *,
        name: str,
        media_url: str,
        source_language: str | None = None,
        target_language: str = "zh",
        auto_workflow: bool = True,
    ) -> Project:
        project_id = f"proj_{uuid4().hex}"
        now = datetime.now(tz=timezone.utc)
        project = Project(
            id=project_id,
            name=name,
            media_url=media_url,
            source_language=source_language,
            target_language=target_language,
            auto_workflow=auto_workflow,
            status=ProjectStatus.PENDING,
            current_stage=0,
            artifacts={},
            stage_runs=[],
            created_at=now,
            updated_at=now,
        )
        await self.project_repo.create(project)
        return await self._hydrate_project(project)

    async def list_projects(self) -> list[Project]:
        projects = await self.project_repo.list(limit=200, offset=0)
        out: list[Project] = []
        for p in projects:
            out.append(await self._hydrate_project(p))
        return out

    async def get_project(self, project_id: str) -> Project | None:
        p = await self.project_repo.get(project_id)
        if p is None:
            return None
        return await self._hydrate_project(p)

    async def save_project(self, project: Project) -> None:
        await self.project_repo.update(project)

    async def delete_project(self, project_id: str) -> bool:
        removed = await self.project_repo.delete(project_id)
        if bool(removed):
            try:
                await BlobStore(self.settings).release_project_files(project_id)
            except Exception as exc:
                logger.warning("failed to release blob refs for project %s: %s", project_id, exc)
        return bool(removed)

    async def enqueue_run_stage(self, project_id: str, stage: StageName) -> None:
        await self.redis.lpush(
            self._queue_key(),
            json.dumps({"type": "run_stage", "project_id": project_id, "stage": stage.value}),
        )

    async def enqueue_run_all(self, project_id: str, from_stage: StageName | None = None) -> None:
        payload: dict[str, str] = {"type": "run_all", "project_id": project_id}
        if from_stage is not None:
            payload["from_stage"] = from_stage.value
        await self.redis.lpush(self._queue_key(), json.dumps(payload))
