from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from subflow.config import Settings
from subflow.models.project import StageName
from subflow.storage import get_artifact_store

from ._deps import _projects_module, pool, service

router = APIRouter()


@router.get("/{project_id}/artifacts/{stage}")
async def get_artifacts(request: Request, project_id: str, stage: StageName) -> dict:
    project = await service(request).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    projects_module = _projects_module()
    stage_run_repo = projects_module.StageRunRepository(pool(request))
    sr = await stage_run_repo.get(project_id, stage.value)
    return {
        "project_id": project_id,
        "stage": stage.value,
        "artifacts": dict(sr.output_artifacts or {}) if sr is not None else {},
    }


@router.get("/{project_id}/artifacts/{stage}/{artifact_name}")
async def get_artifact_content(
    request: Request,
    project_id: str,
    stage: StageName,
    artifact_name: str,
) -> dict[str, Any]:
    project = await service(request).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    if "/" in artifact_name or "\\" in artifact_name or ".." in artifact_name:
        raise HTTPException(status_code=400, detail="invalid artifact name")

    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    store = get_artifact_store(settings)
    try:
        if artifact_name.endswith(".json"):
            data = await store.load_json(project_id, stage.value, artifact_name)
            return {
                "project_id": project_id,
                "stage": stage.value,
                "name": artifact_name,
                "kind": "json",
                "data": data,
            }
        text = await store.load_text(project_id, stage.value, artifact_name)
        return {
            "project_id": project_id,
            "stage": stage.value,
            "name": artifact_name,
            "kind": "text",
            "data": text,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="artifact not found") from None
