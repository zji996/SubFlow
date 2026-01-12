from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ._deps import service, to_response
from .schemas import CreateProjectRequest, ProjectResponse

router = APIRouter()


@router.post("", response_model=ProjectResponse)
async def create_project(request: Request, payload: CreateProjectRequest) -> ProjectResponse:
    project = await service(request).create_project(
        name=payload.name,
        media_url=payload.media_url,
        source_language=payload.source_language,
        target_language=payload.target_language,
        auto_workflow=payload.auto_workflow,
    )
    return to_response(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(request: Request) -> list[ProjectResponse]:
    projects = await service(request).list_projects()
    return [to_response(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(request: Request, project_id: str) -> ProjectResponse:
    project = await service(request).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return to_response(project)


@router.delete("/{project_id}")
async def delete_project(request: Request, project_id: str) -> dict:
    ok = await service(request).delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="project not found")
    return {"deleted": True, "project_id": project_id}
