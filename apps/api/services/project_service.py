"""Project CRUD and queue operations backed by Redis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from redis.asyncio import Redis

from subflow.models.project import Project, ProjectStatus, StageName


class ProjectService:
    def __init__(self, redis: Redis):
        self.redis = redis

    @staticmethod
    def _project_key(project_id: str) -> str:
        return f"subflow:project:{project_id}"

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
    ) -> Project:
        project_id = f"proj_{uuid4().hex}"
        now = datetime.now(tz=timezone.utc).isoformat()
        project = Project(
            id=project_id,
            name=name,
            media_url=media_url,
            source_language=source_language,
            target_language=target_language,
            status=ProjectStatus.PENDING,
            current_stage=0,
            artifacts={},
            stage_runs=[],
        )
        data = project.to_dict()
        data["created_at"] = now
        data["updated_at"] = now

        await self.redis.set(self._project_key(project_id), json.dumps(data), ex=30 * 24 * 3600)
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
        raw = await self.redis.get(self._project_key(project_id))
        if not raw:
            return None
        return Project.from_dict(json.loads(raw))

    async def save_project(self, project: Project) -> None:
        project.touch()
        await self.redis.set(
            self._project_key(project.id), json.dumps(project.to_dict()), ex=30 * 24 * 3600
        )
        await self.redis.sadd(self._index_key(), project.id)

    async def delete_project(self, project_id: str) -> bool:
        removed = await self.redis.delete(self._project_key(project_id))
        await self.redis.srem(self._index_key(), project_id)
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
