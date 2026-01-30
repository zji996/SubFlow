"""Worker startup recovery helpers."""

from __future__ import annotations

import logging

from subflow.config import Settings
from subflow.models.project import ProjectStatus, StageName, StageRunStatus
from subflow.repositories import DatabasePool, ProjectRepository, StageRunRepository

logger = logging.getLogger(__name__)


_STAGE_ORDER: list[StageName] = [
    StageName.AUDIO_PREPROCESS,
    StageName.VAD,
    StageName.ASR,
    StageName.LLM_ASR_CORRECTION,
    StageName.LLM,
]

_STAGE_INDEX: dict[StageName, int] = {s: i + 1 for i, s in enumerate(_STAGE_ORDER)}


def _infer_current_stage_from_runs(stage_runs) -> int:  # noqa: ANN001
    by_stage = {sr.stage: sr for sr in list(stage_runs or [])}
    inferred = 0
    for s in _STAGE_ORDER:
        sr = by_stage.get(s)
        if sr is not None and sr.status == StageRunStatus.COMPLETED:
            inferred = max(inferred, _STAGE_INDEX[s])
    return int(inferred)


def _all_required_stages_completed(stage_runs) -> bool:  # noqa: ANN001
    by_stage = {sr.stage: sr for sr in list(stage_runs or [])}
    return all(
        by_stage.get(s) is not None and by_stage[s].status == StageRunStatus.COMPLETED
        for s in _STAGE_ORDER
    )


async def recover_orphan_projects(
    *, settings: Settings, max_age_minutes: int = 10, limit: int = 200
) -> int:
    """Fix projects stuck in processing after a worker crash.

    Criteria:
    - Project is still in `processing`
    - `updated_at` is older than `max_age_minutes`
    - All required stage_runs are `completed`
    """
    pool = await DatabasePool.get_pool(settings)
    project_repo = ProjectRepository(pool)
    stage_run_repo = StageRunRepository(pool)

    candidates = await project_repo.find_stale_processing(
        max_age_minutes=max_age_minutes, limit=limit
    )
    if not candidates:
        return 0

    recovered = 0
    for project in candidates:
        stage_runs = await stage_run_repo.list_by_project(project.id)
        inferred_stage = _infer_current_stage_from_runs(stage_runs)
        all_done = _all_required_stages_completed(stage_runs)

        new_stage = max(int(project.current_stage or 0), int(inferred_stage or 0))
        if all_done:
            logger.info(
                "recovering orphan project (project_id=%s, old_stage=%s, new_stage=%s)",
                project.id,
                project.current_stage,
                new_stage,
            )
            await project_repo.update_status(
                project.id,
                ProjectStatus.COMPLETED.value,
                current_stage=new_stage,
                error_message=None,
            )
            recovered += 1
        elif inferred_stage > int(project.current_stage or 0):
            logger.info(
                "reconciling stale project stage (project_id=%s, old_stage=%s, new_stage=%s)",
                project.id,
                project.current_stage,
                new_stage,
            )
            await project_repo.update_status(
                project.id,
                ProjectStatus.PROCESSING.value,
                current_stage=new_stage,
                error_message=None,
            )

    return recovered
