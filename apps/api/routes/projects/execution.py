from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from subflow.models.project import StageName

from ._deps import service, to_response
from .schemas import ProjectResponse, RunStageRequest

router = APIRouter()


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


@router.post("/{project_id}/run-all", response_model=ProjectResponse)
async def run_all(request: Request, project_id: str) -> ProjectResponse:
    svc = service(request)
    project = await svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    await svc.enqueue_run_all(project_id)
    return to_response(project)
