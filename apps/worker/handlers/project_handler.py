"""Project task processing handler."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from redis.asyncio import Redis

from subflow.config import Settings
from subflow.models.project import Project, ProjectStatus, StageName
from subflow.pipeline import PipelineOrchestrator
from subflow.services import ProjectStore, StorageService
from subflow.storage import LocalArtifactStore


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

    project_store = ProjectStore(redis)
    project = await project_store.get(project_id)
    if project is None:
        return

    store = LocalArtifactStore(settings.data_dir)
    orchestrator = PipelineOrchestrator(settings, store=store)

    try:
        project.status = ProjectStatus.PROCESSING
        await project_store.save(project)

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
                await project_store.save(project)
        elif typ == "run_stage":
            stage_raw = task.get("stage")
            if not stage_raw:
                return
            stage = StageName(str(stage_raw))
            project, _ = await orchestrator.run_stage(project, stage)
            await project_store.save(project)
            if project.auto_workflow and stage != StageName.EXPORT:
                project, _ = await orchestrator.run_stage(project, StageName.EXPORT)
            elif not project.auto_workflow and project.status == ProjectStatus.PROCESSING:
                project.status = ProjectStatus.PAUSED
        else:
            return

        await _maybe_upload_export(settings, project)
        await project_store.save(project)

    except Exception as exc:
        project.status = ProjectStatus.FAILED
        project.artifacts.setdefault("errors", []).append(str(exc))
        await project_store.save(project)
