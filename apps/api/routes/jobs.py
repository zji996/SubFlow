"""Jobs API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from redis.asyncio import Redis

from subflow.models.job import JobStatus
from services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


class CreateJobRequest(BaseModel):
    video_url: str
    source_language: str | None = None
    target_language: str = "zh"


class JobResponse(BaseModel):
    id: str
    status: str
    result_url: str | None = None
    error: str | None = None


def _job_service(request: Request) -> JobService:
    redis: Redis = request.app.state.redis
    return JobService(redis=redis)


@router.post("", response_model=JobResponse)
async def create_job(request: Request, payload: CreateJobRequest) -> JobResponse:
    service = _job_service(request)
    job = await service.create_job(
        video_url=payload.video_url,
        source_language=payload.source_language,
        target_language=payload.target_language,
    )
    return JobResponse(id=job["id"], status=job["status"], result_url=job.get("result_url"))


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(request: Request, job_id: str) -> JobResponse:
    service = _job_service(request)
    job = await service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobResponse(
        id=job["id"],
        status=job["status"],
        result_url=job.get("result_url"),
        error=job.get("error"),
    )


@router.get("/{job_id}/result")
async def get_job_result(request: Request, job_id: str) -> RedirectResponse:
    service = _job_service(request)
    job = await service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.get("status") != JobStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="job not completed")
    result_url = job.get("result_url")
    if not result_url:
        raise HTTPException(status_code=404, detail="result not available")
    return RedirectResponse(url=result_url, status_code=307)
