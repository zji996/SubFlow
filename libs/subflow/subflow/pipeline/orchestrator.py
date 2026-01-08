"""Project-based pipeline orchestrator (stage-by-stage execution)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable

from subflow.config import Settings
from subflow.error_codes import ErrorCode
from subflow.exceptions import ConfigurationError, ProviderError, StageExecutionError
from subflow.models.serializers import (
    deserialize_asr_corrected_segments,
    deserialize_asr_merged_chunks,
    deserialize_asr_segments,
    deserialize_semantic_chunks,
    deserialize_vad_segments,
)
from subflow.models.project import (
    Project,
    ProjectStatus,
    StageName,
    StageRun,
    StageRunStatus,
)
from subflow.models.segment import ASRCorrectedSegment
from subflow.pipeline.context import PipelineContext
from subflow.pipeline.stage_runners import RUNNERS
from subflow.storage.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)

ProjectUpdateHook = Callable[[Project], Awaitable[None]]


_STAGE_ORDER: list[StageName] = [
    StageName.AUDIO_PREPROCESS,
    StageName.VAD,
    StageName.ASR,
    StageName.LLM_ASR_CORRECTION,
    StageName.LLM,
    StageName.EXPORT,
]

_STAGE_INDEX: dict[StageName, int] = {s: i + 1 for i, s in enumerate(_STAGE_ORDER)}


class PipelineOrchestrator:
    """Project-first orchestrator with artifact persistence."""

    def __init__(
        self,
        settings: Settings,
        store: ArtifactStore,
        *,
        on_project_update: ProjectUpdateHook | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self._on_project_update = on_project_update

    async def _notify_update(self, project: Project) -> None:
        if self._on_project_update is not None:
            await self._on_project_update(project)

    @staticmethod
    def _infer_error_code(stage: StageName, exc: BaseException) -> str:
        if isinstance(exc, StageExecutionError) and exc.error_code is not None:
            return str(exc.error_code)
        if isinstance(exc, ProviderError) and exc.error_code is not None:
            return str(exc.error_code)
        if isinstance(exc, ConfigurationError):
            return ErrorCode.INVALID_MEDIA.value

        if stage == StageName.AUDIO_PREPROCESS:
            return ErrorCode.AUDIO_PREPROCESS_FAILED.value
        if stage == StageName.VAD:
            return ErrorCode.VAD_FAILED.value
        if stage == StageName.ASR:
            return ErrorCode.ASR_FAILED.value
        if stage in {StageName.LLM_ASR_CORRECTION, StageName.LLM}:
            msg = str(exc).lower()
            if "timeout" in msg or "timed out" in msg:
                return ErrorCode.LLM_TIMEOUT.value
            return ErrorCode.LLM_FAILED.value
        if stage == StageName.EXPORT:
            return ErrorCode.EXPORT_FAILED.value
        return ErrorCode.UNKNOWN.value

    @staticmethod
    def _infer_error_message(exc: BaseException) -> str:
        if isinstance(exc, StageExecutionError):
            return str(exc.message or "")
        if isinstance(exc, ProviderError):
            return str(exc.message or "")
        return str(exc)

    def _base_context(self, project: Project) -> PipelineContext:
        return {
            "project_id": project.id,
            "media_url": project.media_url,
            "source_language": project.source_language,
            "target_language": project.target_language,
        }

    async def _hydrate_context(self, project: Project) -> PipelineContext:
        ctx: PipelineContext = self._base_context(project)

        if project.current_stage >= _STAGE_INDEX[StageName.AUDIO_PREPROCESS]:
            try:
                stage1 = await self.store.load_json(project.id, StageName.AUDIO_PREPROCESS.value, "stage1.json")
                if isinstance(stage1, dict):
                    for key in ("video_path", "audio_path", "vocals_audio_path"):
                        value = stage1.get(key)
                        if value is not None:
                            ctx[key] = str(value)
            except FileNotFoundError:
                pass

        if project.current_stage >= _STAGE_INDEX[StageName.VAD]:
            try:
                vad = await self.store.load_json(project.id, StageName.VAD.value, "vad_segments.json")
                if isinstance(vad, list):
                    ctx["vad_segments"] = deserialize_vad_segments(vad)
            except FileNotFoundError:
                pass
            try:
                regions = await self.store.load_json(project.id, StageName.VAD.value, "vad_regions.json")
                if isinstance(regions, list):
                    ctx["vad_regions"] = deserialize_vad_segments(regions)
            except FileNotFoundError:
                pass

        if project.current_stage >= _STAGE_INDEX[StageName.ASR]:
            try:
                asr = await self.store.load_json(project.id, StageName.ASR.value, "asr_segments.json")
                if isinstance(asr, list):
                    ctx["asr_segments"] = deserialize_asr_segments(asr)
            except FileNotFoundError:
                pass
            try:
                ctx["full_transcript"] = await self.store.load_text(
                    project.id, StageName.ASR.value, "full_transcript.txt"
                )
            except FileNotFoundError:
                pass
            try:
                merged = await self.store.load_json(project.id, StageName.ASR.value, "asr_merged_chunks.json")
                if isinstance(merged, list):
                    ctx["asr_merged_chunks"] = deserialize_asr_merged_chunks(merged)
            except FileNotFoundError:
                pass

        if project.current_stage >= _STAGE_INDEX[StageName.LLM_ASR_CORRECTION]:
            try:
                corrected = await self.store.load_json(
                    project.id,
                    StageName.LLM_ASR_CORRECTION.value,
                    "asr_corrected_segments.json",
                )
                if isinstance(corrected, list):
                    ctx["asr_corrected_segments"] = deserialize_asr_corrected_segments(corrected)
            except FileNotFoundError:
                pass

        if project.current_stage >= _STAGE_INDEX[StageName.LLM]:
            try:
                global_ctx = await self.store.load_json(project.id, StageName.LLM.value, "global_context.json")
                if isinstance(global_ctx, dict):
                    ctx["global_context"] = global_ctx
            except FileNotFoundError:
                pass
            try:
                # Backward compatibility: legacy artifacts stored corrections under the LLM stage.
                if "asr_corrected_segments" not in ctx:
                    corrected = await self.store.load_json(
                        project.id, StageName.LLM.value, "asr_corrected_segments.json"
                    )
                    if isinstance(corrected, list):
                        ctx["asr_corrected_segments"] = deserialize_asr_corrected_segments(corrected)
            except FileNotFoundError:
                pass
            try:
                chunks = await self.store.load_json(project.id, StageName.LLM.value, "semantic_chunks.json")
                if isinstance(chunks, list):
                    ctx["semantic_chunks"] = deserialize_semantic_chunks(chunks)
            except FileNotFoundError:
                pass

        corrected_map: dict[int, ASRCorrectedSegment] = dict(ctx.get("asr_corrected_segments") or {})
        if corrected_map and ctx.get("asr_segments"):
            for seg in list(ctx.get("asr_segments") or []):
                corrected = corrected_map.get(int(seg.id))
                if corrected is not None:
                    seg.text = str(corrected.text or "")
            ctx["full_transcript"] = " ".join(
                seg.text for seg in list(ctx.get("asr_segments") or []) if (seg.text or "").strip()
            )

        return ctx

    async def run_stage(self, project: Project, stage: StageName) -> tuple[Project, PipelineContext]:
        target_index = _STAGE_INDEX[stage]
        if project.current_stage >= target_index:
            logger.info("orchestrator skip (project_id=%s, stage=%s)", project.id, stage.value)
            ctx = await self._hydrate_context(project)
            return project, ctx

        project.status = ProjectStatus.PROCESSING
        ctx = await self._hydrate_context(project)

        for stage_name in _STAGE_ORDER:
            idx = _STAGE_INDEX[stage_name]
            if idx <= project.current_stage:
                continue
            if idx > target_index:
                break

            run = StageRun(stage=stage_name, status=StageRunStatus.RUNNING)
            run.started_at = run.started_at or datetime.now(tz=timezone.utc)
            run.progress = 0
            run.progress_message = "running"
            project.stage_runs.append(run)
            await self._notify_update(project)

            try:
                logger.info("stage start (project_id=%s, stage=%s)", project.id, stage_name.value)
                runner = RUNNERS.get(stage_name)
                if runner is None:  # pragma: no cover
                    raise ValueError(f"Unknown stage: {stage_name}")
                ctx, artifacts = await runner.run(
                    settings=self.settings,
                    store=self.store,
                    project=project,
                    ctx=ctx,
                )
                project.artifacts[stage_name.value] = artifacts
                run.output_artifacts = dict(artifacts)

                project.current_stage = idx
                run.status = StageRunStatus.COMPLETED
                run.completed_at = datetime.now(tz=timezone.utc)
                if run.started_at is not None and run.completed_at is not None:
                    run.duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000)
                run.progress = 100
                run.progress_message = "completed"
                logger.info(
                    "stage done (project_id=%s, stage=%s, duration_ms=%s)",
                    project.id,
                    stage_name.value,
                    run.duration_ms,
                )
                await self._notify_update(project)

            except Exception as exc:
                logger.exception("stage failed (project_id=%s, stage=%s)", project.id, stage_name.value)
                run.status = StageRunStatus.FAILED
                run.completed_at = datetime.now(tz=timezone.utc)
                if run.started_at is not None and run.completed_at is not None:
                    run.duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000)
                run.error_code = self._infer_error_code(stage_name, exc)
                run.error_message = self._infer_error_message(exc)
                run.error = str(exc)
                run.progress_message = "failed"
                project.status = ProjectStatus.FAILED
                await self._notify_update(project)
                if isinstance(exc, StageExecutionError):
                    raise StageExecutionError(
                        exc.stage,
                        exc.message,
                        project_id=project.id,
                        error_code=exc.error_code,
                    ) from exc
                raise StageExecutionError(
                    stage_name.value,
                    str(exc),
                    project_id=project.id,
                    error_code=run.error_code,
                ) from exc

        if project.current_stage >= _STAGE_INDEX[StageName.EXPORT]:
            project.status = ProjectStatus.COMPLETED

        return project, ctx

    async def run_all(self, project: Project, from_stage: StageName | None = None) -> tuple[Project, PipelineContext]:
        if from_stage is not None:
            project.current_stage = min(project.current_stage, _STAGE_INDEX[from_stage] - 1)
        return await self.run_stage(project, StageName.EXPORT)
