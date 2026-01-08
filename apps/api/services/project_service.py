"""Project CRUD and queue operations backed by Redis."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from redis.asyncio import Redis

from subflow.config import Settings
from subflow.models.project import Project, ProjectStatus, StageName
from subflow.services import BlobStore, ProjectStore

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, redis: Redis, settings: Settings):
        self.redis = redis
        self.settings = settings
        self.store = ProjectStore(
            redis,
            ttl_seconds=int(settings.redis_project_ttl_days) * 24 * 3600,
        )

    @staticmethod
    def _index_key() -> str:
        return "subflow:projects:index"

    @staticmethod
    def _queue_key() -> str:
        return "subflow:projects:queue"

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
        await self.store.save(project)
        await self.redis.sadd(self._index_key(), project_id)
        return project

    async def list_projects(self) -> list[Project]:
        ids = sorted(list(await self.redis.smembers(self._index_key())))
        projects: list[Project] = []
        for pid in ids:
            p = await self.get_project(pid)
            if p is not None:
                projects.append(p)
        return projects

    async def get_project(self, project_id: str) -> Project | None:
        return await self.store.get(project_id)

    async def save_project(self, project: Project) -> None:
        await self.store.save(project)
        await self.redis.sadd(self._index_key(), project.id)

    async def delete_project(self, project_id: str) -> bool:
        removed = await self.store.delete(project_id)
        await self.redis.srem(self._index_key(), project_id)
        if removed:
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
