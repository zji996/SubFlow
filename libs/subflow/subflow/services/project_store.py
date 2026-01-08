"""Project persistence backed by Redis."""

from __future__ import annotations

import json

from redis.asyncio import Redis

from subflow.models.project import Project


class ProjectStore:
    def __init__(self, redis_client: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis_client
        self._ttl_seconds = max(1, int(ttl_seconds))

    @staticmethod
    def key(project_id: str) -> str:
        return f"subflow:project:{project_id}"

    async def get(self, project_id: str) -> Project | None:
        raw = await self._redis.get(self.key(project_id))
        if not raw:
            return None
        return Project.from_dict(json.loads(raw))

    async def save(self, project: Project) -> None:
        project.touch()
        await self._redis.set(self.key(project.id), json.dumps(project.to_dict()), ex=self._ttl_seconds)

    async def delete(self, project_id: str) -> bool:
        removed = await self._redis.delete(self.key(project_id))
        return bool(removed)
