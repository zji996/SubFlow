"""Project task processing handler."""

from __future__ import annotations

import logging
from typing import Any

from redis.asyncio import Redis

from subflow.config import Settings
from subflow.models.project import ProjectStatus, StageName
from subflow.pipeline import PipelineOrchestrator
from subflow.services import ProjectStore
from subflow.storage import get_artifact_store

logger = logging.getLogger(__name__)


async def process_project_task(task: dict[str, Any], redis: Redis, settings: Settings) -> None:
    project_id = str(task.get("project_id", "")).strip()
    if not project_id:
        return

    project_store = ProjectStore(
        redis,
        ttl_seconds=int(settings.redis_project_ttl_days) * 24 * 3600,
    )
    project = await project_store.get(project_id)
    if project is None:
        return

    store = get_artifact_store(settings)
    orchestrator = PipelineOrchestrator(settings, store=store, on_project_update=project_store.save)

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
            ]
            start_index = 0
            if from_stage is not None:
                try:
                    start_index = max(0, stage_order.index(from_stage))
                except ValueError:
                    start_index = 0
            for s in stage_order[start_index:]:
                project, _ = await orchestrator.run_stage(project, s)
                await project_store.save(project)
        elif typ == "run_stage":
            stage_raw = task.get("stage")
            if not stage_raw:
                return
            stage = StageName(str(stage_raw))
            if stage == StageName.EXPORT:
                stage = StageName.LLM
            project, _ = await orchestrator.run_stage(project, stage)
            await project_store.save(project)
            if project.auto_workflow and stage != StageName.LLM:
                project, _ = await orchestrator.run_stage(project, StageName.LLM)
            elif not project.auto_workflow and project.status == ProjectStatus.PROCESSING:
                project.status = ProjectStatus.PAUSED
        else:
            return
        await project_store.save(project)

    except Exception as exc:
        project.status = ProjectStatus.FAILED
        project.artifacts.setdefault("errors", []).append(str(exc))
        await project_store.save(project)
