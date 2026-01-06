"""Projects API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from services.project_service import ProjectService
from subflow.models.project import Project, StageName

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = "Untitled"
    media_url: str
    source_language: str | None = Field(default=None, alias="language")
    target_language: str = "zh"


class RunStageRequest(BaseModel):
    stage: StageName | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    media_url: str
    source_language: str | None = None
    target_language: str
    status: str
    current_stage: int
    artifacts: dict
    stage_runs: list[dict]


def _service(request: Request) -> ProjectService:
    redis: Redis = request.app.state.redis
    return ProjectService(redis=redis)


def _to_response(project: Project) -> ProjectResponse:
    data = project.to_dict()
    return ProjectResponse(
        id=data["id"],
        name=data["name"],
        media_url=data["media_url"],
        source_language=data.get("source_language"),
        target_language=data.get("target_language", "zh"),
        status=data.get("status", "pending"),
        current_stage=int(data.get("current_stage") or 0),
        artifacts=data.get("artifacts") or {},
        stage_runs=data.get("stage_runs") or [],
    )


@router.post("", response_model=ProjectResponse)
async def create_project(request: Request, payload: CreateProjectRequest) -> ProjectResponse:
    service = _service(request)
    project = await service.create_project(
        name=payload.name,
        media_url=payload.media_url,
        source_language=payload.source_language,
        target_language=payload.target_language,
    )
    return _to_response(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(request: Request) -> list[ProjectResponse]:
    service = _service(request)
    projects = await service.list_projects()
    return [_to_response(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(request: Request, project_id: str) -> ProjectResponse:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return _to_response(project)


@router.post("/{project_id}/run", response_model=ProjectResponse)
async def run_project(request: Request, project_id: str, payload: RunStageRequest) -> ProjectResponse:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    stage = payload.stage
    if stage is None:
        next_stage = max(0, int(project.current_stage)) + 1
        stage = {
            1: StageName.AUDIO_PREPROCESS,
            2: StageName.VAD,
            3: StageName.ASR,
            4: StageName.LLM,
            5: StageName.EXPORT,
        }.get(next_stage)
        if stage is None:
            raise HTTPException(status_code=409, detail="project already completed")

    await service.enqueue_run_stage(project_id, stage)
    return _to_response(project)


@router.post("/{project_id}/run-all", response_model=ProjectResponse)
async def run_all(request: Request, project_id: str) -> ProjectResponse:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    await service.enqueue_run_all(project_id)
    return _to_response(project)


@router.get("/{project_id}/artifacts/{stage}")
async def get_artifacts(request: Request, project_id: str, stage: StageName) -> dict:
    service = _service(request)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    artifacts = dict(project.artifacts or {})
    return {"project_id": project_id, "stage": stage.value, "artifacts": artifacts.get(stage.value)}


@router.delete("/{project_id}")
async def delete_project(request: Request, project_id: str) -> dict:
    service = _service(request)
    ok = await service.delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="project not found")
    return {"deleted": True, "project_id": project_id}

