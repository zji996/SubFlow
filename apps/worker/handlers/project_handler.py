"""Project task processing handler."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from redis.asyncio import Redis

from subflow.config import Settings
from subflow.models.project import Project, ProjectStatus, StageName
from subflow.pipeline import PipelineOrchestrator
from subflow.services import StorageService
from subflow.storage import LocalArtifactStore


def _project_key(project_id: str) -> str:
    return f"subflow:project:{project_id}"


async def _get_project(redis: Redis, project_id: str) -> Project | None:
    raw = await redis.get(_project_key(project_id))
    if not raw:
        return None
    return Project.from_dict(json.loads(raw))


async def _save_project(redis: Redis, project: Project) -> None:
    project.updated_at = datetime.now(tz=timezone.utc)
    await redis.set(_project_key(project.id), json.dumps(project.to_dict()), ex=30 * 24 * 3600)


async def _maybe_upload_export(settings: Settings, project: Project) -> None:
    export = (project.artifacts or {}).get(StageName.EXPORT.value) or {}
    local_path = export.get("subtitles.srt")
    if not local_path:
        return

    try:
        path = Path(str(local_path))
        if not path.exists():
            return
    except Exception:
        return

    if not settings.s3_endpoint or not settings.s3_bucket_name:
        return

    storage = StorageService(
        endpoint=settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        bucket=settings.s3_bucket_name,
    )
    remote_key = f"projects/{project.id}/subtitles.srt"
    await storage.upload_file(str(path), remote_key)
    url = await storage.get_presigned_url(remote_key, expires_in=24 * 3600)
    export["subtitles.srt_url"] = url
    project.artifacts[StageName.EXPORT.value] = export


async def process_project_task(task: dict[str, Any], redis: Redis, settings: Settings) -> None:
    project_id = str(task.get("project_id", "")).strip()
    if not project_id:
        return

    project = await _get_project(redis, project_id)
    if project is None:
        return

    store = LocalArtifactStore(settings.data_dir)
    orchestrator = PipelineOrchestrator(settings, store=store)

    try:
        project.status = ProjectStatus.PROCESSING
        await _save_project(redis, project)

        typ = str(task.get("type", "")).strip()
        if typ == "run_all":
            from_stage_raw = task.get("from_stage")
            from_stage = StageName(str(from_stage_raw)) if from_stage_raw else None
            stage_order = [
                StageName.AUDIO_PREPROCESS,
                StageName.VAD,
                StageName.ASR,
                StageName.LLM_ASR_CORRECTION,
                StageName.LLM,
                StageName.EXPORT,
            ]
            start_index = 0
            if from_stage is not None:
                start_index = max(0, stage_order.index(from_stage))
            for s in stage_order[start_index:]:
                project, _ = await orchestrator.run_stage(project, s)
                await _save_project(redis, project)
        elif typ == "run_stage":
            stage_raw = task.get("stage")
            if not stage_raw:
                return
            stage = StageName(str(stage_raw))
            project, _ = await orchestrator.run_stage(project, stage)
        else:
            return

        await _maybe_upload_export(settings, project)
        await _save_project(redis, project)

    except Exception as exc:
        project.status = ProjectStatus.FAILED
        project.updated_at = datetime.now(tz=timezone.utc)
        project.artifacts.setdefault("errors", []).append(str(exc))
        await _save_project(redis, project)
