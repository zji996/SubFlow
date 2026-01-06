"""Job CRUD and queue operations backed by Redis (skeleton)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from redis.asyncio import Redis

from subflow.models.job import JobStatus


class JobService:
    def __init__(self, redis: Redis):
        self.redis = redis

    @staticmethod
    def _job_key(job_id: str) -> str:
        return f"subflow:job:{job_id}"

    async def create_job(self, video_url: str, target_language: str = "zh") -> dict:
        job_id = uuid4().hex
        now = datetime.now(tz=timezone.utc).isoformat()
        job = {
            "id": job_id,
            "video_url": video_url,
            "status": JobStatus.PENDING.value,
            "target_language": target_language,
            "created_at": now,
            "updated_at": now,
            "error": None,
            "result_url": None,
        }

        await self.redis.set(self._job_key(job_id), json.dumps(job), ex=7 * 24 * 3600)
        await self.redis.lpush("subflow:jobs", json.dumps({"id": job_id}))
        return job

    async def get_job(self, job_id: str) -> dict | None:
        raw = await self.redis.get(self._job_key(job_id))
        if not raw:
            return None
        return json.loads(raw)

    async def update_job(self, job_id: str, patch: dict) -> dict | None:
        job = await self.get_job(job_id)
        if job is None:
            return None
        job.update(patch)
        job["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        await self.redis.set(self._job_key(job_id), json.dumps(job), ex=7 * 24 * 3600)
        return job
