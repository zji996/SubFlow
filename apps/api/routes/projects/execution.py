from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from subflow.models.project import ProjectStatus, StageName, StageRunStatus

from ._deps import service, to_response
from .schemas import ProjectResponse, RunStageRequest

router = APIRouter()

_STAGE_ORDER: list[StageName] = [
    StageName.AUDIO_PREPROCESS,
    StageName.VAD,
    StageName.ASR,
    StageName.LLM_ASR_CORRECTION,
    StageName.LLM,
]


class RetryStageRequest(BaseModel):
    stage: StageName | None = None


@router.post("/{project_id}/run", response_model=ProjectResponse)
async def run_project(
    request: Request, project_id: str, payload: RunStageRequest
) -> ProjectResponse:
    svc = service(request)
    project = await svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    stage = payload.stage
    if stage == StageName.EXPORT:
        raise HTTPException(status_code=400, detail="export stage has been removed")
    if stage is None:
        if project.status == ProjectStatus.FAILED:
            by_stage = {sr.stage: sr for sr in list(project.stage_runs or [])}
            for s in _STAGE_ORDER:
                run = by_stage.get(s)
                if run is not None and run.status == StageRunStatus.FAILED:
                    stage = s
                    break
        if stage is None:
            next_stage = max(0, int(project.current_stage)) + 1
            stage = {
                1: StageName.AUDIO_PREPROCESS,
                2: StageName.VAD,
                3: StageName.ASR,
                4: StageName.LLM_ASR_CORRECTION,
                5: StageName.LLM,
            }.get(next_stage)
            if stage is None:
                raise HTTPException(status_code=409, detail="project already completed")

    await svc.enqueue_run_stage(project_id, stage)
    return to_response(project)


@router.post("/{project_id}/retry", response_model=ProjectResponse)
async def retry_stage(
    request: Request, project_id: str, payload: RetryStageRequest
) -> ProjectResponse:
    svc = service(request)
    project = await svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if project.status == ProjectStatus.PROCESSING:
        raise HTTPException(status_code=409, detail="project is processing")

    stage = payload.stage
    if stage == StageName.EXPORT:
        raise HTTPException(status_code=400, detail="export stage has been removed")

    by_stage = {sr.stage: sr for sr in list(project.stage_runs or [])}
    if stage is None:
        for s in _STAGE_ORDER:
            run = by_stage.get(s)
            if run is not None and run.status == StageRunStatus.FAILED:
                stage = s
                break
        if stage is None:
            raise HTTPException(status_code=409, detail="no failed stage to retry")
    else:
        run = by_stage.get(stage)
        if run is None:
            raise HTTPException(status_code=409, detail="stage has not been run")
        if run.status != StageRunStatus.FAILED:
            raise HTTPException(status_code=409, detail="stage is not failed")

    await svc.enqueue_retry_stage(project_id, stage)
    return to_response(project)


@router.post("/{project_id}/run-all", response_model=ProjectResponse)
async def run_all(request: Request, project_id: str) -> ProjectResponse:
    svc = service(request)
    project = await svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    await svc.enqueue_run_all(project_id)
    return to_response(project)
