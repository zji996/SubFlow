"""Project task processing handler."""

from __future__ import annotations

import logging
from typing import Any

from redis.asyncio import Redis

from subflow.config import Settings
from subflow.models.project import ProjectStatus, StageName
from subflow.pipeline import PipelineOrchestrator
from subflow.repositories import (
    ASRMergedChunkRepository,
    ASRSegmentRepository,
    DatabasePool,
    GlobalContextRepository,
    ProjectRepository,
    SemanticChunkRepository,
    StageRunRepository,
    VADSegmentRepository,
)
from subflow.storage import get_artifact_store

logger = logging.getLogger(__name__)


async def process_project_task(task: dict[str, Any], redis: Redis, settings: Settings) -> None:
    project_id = str(task.get("project_id", "")).strip()
    if not project_id:
        return

    pool = await DatabasePool.get_pool(settings)
    project_repo = ProjectRepository(pool)
    stage_run_repo = StageRunRepository(pool)
    vad_repo = VADSegmentRepository(pool)
    asr_repo = ASRSegmentRepository(pool)
    asr_merged_chunk_repo = ASRMergedChunkRepository(pool)
    global_context_repo = GlobalContextRepository(pool)
    semantic_chunk_repo = SemanticChunkRepository(pool)

    project = await project_repo.get(project_id)
    if project is None:
        return

    store = get_artifact_store(settings)
    orchestrator = PipelineOrchestrator(
        settings,
        store=store,
        project_repo=project_repo,
        stage_run_repo=stage_run_repo,
        vad_repo=vad_repo,
        asr_repo=asr_repo,
        asr_merged_chunk_repo=asr_merged_chunk_repo,
        global_context_repo=global_context_repo,
        semantic_chunk_repo=semantic_chunk_repo,
    )

    try:
        await project_repo.update_status(
            project_id, ProjectStatus.PROCESSING.value, project.current_stage
        )

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
        elif typ == "run_stage":
            stage_raw = task.get("stage")
            if not stage_raw:
                return
            stage = StageName(str(stage_raw))
            if stage == StageName.EXPORT:
                stage = StageName.LLM
            project, _ = await orchestrator.run_stage(project, stage)
            if project.auto_workflow and stage != StageName.LLM:
                project, _ = await orchestrator.run_stage(project, StageName.LLM)
            elif not project.auto_workflow and project.status == ProjectStatus.PROCESSING:
                project.status = ProjectStatus.PAUSED
                await project_repo.update_status(
                    project_id, ProjectStatus.PAUSED.value, project.current_stage
                )
        else:
            return
        await project_repo.update_status(project_id, project.status.value, project.current_stage)

    except Exception as exc:
        await project_repo.update_status(
            project_id, ProjectStatus.FAILED.value, project.current_stage, error_message=str(exc)
        )
