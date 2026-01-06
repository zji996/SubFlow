"""Job processing handler (skeleton)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from redis.asyncio import Redis

from libs.subflow.config import Settings
from libs.subflow.models.job import JobStatus
from libs.subflow.pipeline import PipelineExecutor


def _job_key(job_id: str) -> str:
    return f"subflow:job:{job_id}"


async def _get_job(redis: Redis, job_id: str) -> dict | None:
    raw = await redis.get(_job_key(job_id))
    if not raw:
        return None
    return json.loads(raw)


async def _update_job(redis: Redis, job_id: str, patch: dict) -> dict | None:
    job = await _get_job(redis, job_id)
    if job is None:
        return None
    job.update(patch)
    job["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
    await redis.set(_job_key(job_id), json.dumps(job), ex=7 * 24 * 3600)
    return job


async def process_job(job_data: dict, pipeline: PipelineExecutor, redis: Redis, settings: Settings) -> None:
    """处理单个翻译任务"""
    job_id = str(job_data.get("id", ""))
    if not job_id:
        return

    job = await _get_job(redis, job_id)
    if job is None:
        return

    try:
        await _update_job(redis, job_id, {"status": JobStatus.PROCESSING.value, "error": None})

        final_context = await pipeline.run(
            {
                "job_id": job_id,
                "video_url": job["video_url"],
                "target_language": job.get("target_language", "zh"),
                "source_language": job.get("source_language"),
            }
        )

        result_path = str(final_context.get("result_path", f"jobs/{job_id}/subtitles.srt"))
        result_url = (
            f"{settings.s3_endpoint.rstrip('/')}/{settings.s3_bucket_name}/{result_path.lstrip('/')}"
        )
        await redis.set(f"subflow:job_result:{job_id}", final_context.get("subtitle_text", ""), ex=7 * 24 * 3600)
        await _update_job(
            redis,
            job_id,
            {
                "status": JobStatus.COMPLETED.value,
                "result_url": result_url,
            },
        )
    except Exception as exc:
        await _update_job(
            redis,
            job_id,
            {"status": JobStatus.FAILED.value, "error": str(exc)},
        )

