"""Project-based pipeline orchestrator (stage-by-stage execution)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable

from subflow.config import Settings
from subflow.error_codes import ErrorCode
from subflow.exceptions import ConfigurationError, ProviderError, StageExecutionError
from subflow.models.project import (
    Project,
    ProjectStatus,
    StageName,
    StageRun,
    StageRunStatus,
)
from subflow.models.segment import ASRCorrectedSegment
from subflow.pipeline.context import PipelineContext, ProgressReporter
from subflow.pipeline.stage_runners import RUNNERS
from subflow.repositories import (
    ASRMergedChunkRepository,
    ASRSegmentRepository,
    GlobalContextRepository,
    ProjectRepository,
    SemanticChunkRepository,
    StageRunRepository,
    VADSegmentRepository,
)
from subflow.storage.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)

ProjectUpdateHook = Callable[[Project], Awaitable[None]]


_STAGE_ORDER: list[StageName] = [
    StageName.AUDIO_PREPROCESS,
    StageName.VAD,
    StageName.ASR,
    StageName.LLM_ASR_CORRECTION,
    StageName.LLM,
]

_STAGE_INDEX: dict[StageName, int] = {s: i + 1 for i, s in enumerate(_STAGE_ORDER)}


class _StageRunProgressReporter(ProgressReporter):
    def __init__(
        self,
        *,
        project: Project,
        stage_run: StageRun,
        notify_update: Callable[[Project], Awaitable[None]],
        min_percent_step: int = 5,
        min_interval_s: float = 2.0,
    ) -> None:
        self._project = project
        self._stage_run = stage_run
        self._notify_update = notify_update
        self._min_percent_step = max(1, int(min_percent_step))
        self._min_interval_s = max(0.0, float(min_interval_s))
        self._lock = asyncio.Lock()
        self._last_progress = int(stage_run.progress or 0)
        self._last_update_at = 0.0

    async def report(self, progress: int, message: str) -> None:
        pct = int(progress)
        if pct < 0:
            pct = 0
        if pct > 100:
            pct = 100
        msg = str(message or "").strip() or "running"

        now = time.monotonic()
        async with self._lock:
            if pct < self._last_progress:
                pct = self._last_progress

            should_emit = False
            if pct >= 100:
                should_emit = True
            elif pct >= self._last_progress + self._min_percent_step:
                should_emit = True
            elif self._min_interval_s > 0 and now - self._last_update_at >= self._min_interval_s:
                should_emit = True

            if not should_emit:
                return

            self._stage_run.progress = pct
            self._stage_run.progress_message = msg
            self._last_progress = pct
            self._last_update_at = now
            await self._notify_update(self._project)


class PipelineOrchestrator:
    """Project-first orchestrator with artifact persistence."""

    def __init__(
        self,
        settings: Settings,
        store: ArtifactStore,
        *,
        project_repo: ProjectRepository,
        stage_run_repo: StageRunRepository,
        vad_repo: VADSegmentRepository,
        asr_repo: ASRSegmentRepository,
        asr_merged_chunk_repo: ASRMergedChunkRepository,
        global_context_repo: GlobalContextRepository,
        semantic_chunk_repo: SemanticChunkRepository,
        on_project_update: ProjectUpdateHook | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.project_repo = project_repo
        self.stage_run_repo = stage_run_repo
        self.vad_repo = vad_repo
        self.asr_repo = asr_repo
        self.asr_merged_chunk_repo = asr_merged_chunk_repo
        self.global_context_repo = global_context_repo
        self.semantic_chunk_repo = semantic_chunk_repo
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
            media_files = dict(getattr(project, "media_files", {}) or {})
            if media_files:
                for k, ctx_key in (("video", "video_path"), ("audio", "audio_path"), ("vocals", "vocals_audio_path")):
                    entry = media_files.get(k)
                    if isinstance(entry, dict):
                        path = entry.get("path")
                        if path:
                            ctx[ctx_key] = str(path)
            if not (ctx.get("video_path") and ctx.get("audio_path") and ctx.get("vocals_audio_path")):
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
            ctx["vad_segments"] = await self.vad_repo.get_by_project(project.id)

        if project.current_stage >= _STAGE_INDEX[StageName.ASR]:
            ctx["asr_segments"] = await self.asr_repo.get_by_project(project.id, use_corrected=False)
            ctx["full_transcript"] = " ".join(
                seg.text for seg in list(ctx.get("asr_segments") or []) if (seg.text or "").strip()
            )
            merged_chunks = await self.asr_merged_chunk_repo.get_by_project(project.id)
            if merged_chunks:
                ctx["asr_merged_chunks"] = merged_chunks
            else:
                try:
                    merged = await self.store.load_json(project.id, StageName.ASR.value, "asr_merged_chunks.json")
                    if isinstance(merged, list):
                        from subflow.models.serializers import deserialize_asr_merged_chunks

                        ctx["asr_merged_chunks"] = deserialize_asr_merged_chunks(merged)
                except FileNotFoundError:
                    pass

        if project.current_stage >= _STAGE_INDEX[StageName.LLM_ASR_CORRECTION]:
            corrected_map = await self.asr_repo.get_corrected_map(project.id)
            if corrected_map:
                full: dict[int, ASRCorrectedSegment] = {}
                if ctx.get("asr_segments"):
                    for seg in list(ctx.get("asr_segments") or []):
                        seg_id = int(seg.id)
                        if seg_id in corrected_map:
                            seg.text = str(corrected_map[seg_id] or "")
                        full[seg_id] = ASRCorrectedSegment(id=seg_id, asr_segment_id=seg_id, text=str(seg.text or ""))
                ctx["asr_corrected_segments"] = full
                ctx["full_transcript"] = " ".join(
                    seg.text for seg in list(ctx.get("asr_segments") or []) if (seg.text or "").strip()
                )

        if project.current_stage >= _STAGE_INDEX[StageName.LLM]:
            global_ctx = await self.global_context_repo.get(project.id)
            if global_ctx is not None:
                ctx["global_context"] = dict(global_ctx)
            ctx["semantic_chunks"] = await self.semantic_chunk_repo.get_by_project(project.id)

        return ctx

    @staticmethod
    def _upsert_stage_run(project: Project, stage_run: StageRun) -> None:
        for i, sr in enumerate(list(project.stage_runs or [])):
            if sr.stage == stage_run.stage:
                project.stage_runs[i] = stage_run
                return
        project.stage_runs.append(stage_run)

    async def run_stage(self, project: Project, stage: StageName) -> tuple[Project, PipelineContext]:
        if stage not in _STAGE_INDEX:
            raise ValueError(f"Unknown stage: {stage}")
        db_project = await self.project_repo.get(project.id)
        if db_project is None:
            raise StageExecutionError(stage.value, "project not found", project_id=project.id)
        project = db_project
        project.stage_runs = await self.stage_run_repo.list_by_project(project.id)

        target_index = _STAGE_INDEX[stage]
        if project.current_stage >= target_index:
            logger.info("orchestrator skip (project_id=%s, stage=%s)", project.id, stage.value)
            ctx = await self._hydrate_context(project)
            return project, ctx

        project.status = ProjectStatus.PROCESSING
        await self.project_repo.update_status(project.id, ProjectStatus.PROCESSING.value, project.current_stage)
        ctx = await self._hydrate_context(project)

        for stage_name in _STAGE_ORDER:
            idx = _STAGE_INDEX[stage_name]
            if idx <= project.current_stage:
                continue
            if idx > target_index:
                break

            run = StageRun(stage=stage_name, status=StageRunStatus.RUNNING)
            run.started_at = datetime.now(tz=timezone.utc)
            run.progress = 0
            run.progress_message = "running"
            self._upsert_stage_run(project, run)
            await self.stage_run_repo.mark_running(project.id, stage_name.value)

            async def _notify_progress(_project: Project) -> None:
                await self.stage_run_repo.set_progress(
                    _project.id,
                    stage_name.value,
                    progress=int(run.progress or 0),
                    message=str(run.progress_message or "running"),
                )
                await self._notify_update(_project)

            await self._notify_update(project)

            try:
                logger.info("stage start (project_id=%s, stage=%s)", project.id, stage_name.value)
                runner = RUNNERS.get(stage_name)
                if runner is None:  # pragma: no cover
                    raise ValueError(f"Unknown stage: {stage_name}")
                progress_reporter = _StageRunProgressReporter(
                    project=project,
                    stage_run=run,
                    notify_update=_notify_progress,
                )
                ctx, artifacts = await runner.run(
                    settings=self.settings,
                    store=self.store,
                    project_repo=self.project_repo,
                    vad_repo=self.vad_repo,
                    asr_repo=self.asr_repo,
                    asr_merged_chunk_repo=self.asr_merged_chunk_repo,
                    global_context_repo=self.global_context_repo,
                    semantic_chunk_repo=self.semantic_chunk_repo,
                    project=project,
                    ctx=ctx,
                    progress_reporter=progress_reporter,
                )
                run.output_artifacts = dict(artifacts)

                project.current_stage = idx
                run.status = StageRunStatus.COMPLETED
                run.completed_at = datetime.now(tz=timezone.utc)
                if run.started_at is not None and run.completed_at is not None:
                    run.duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000)
                run.progress = 100
                run.progress_message = "completed"
                await self.stage_run_repo.mark_completed(
                    project.id,
                    stage_name.value,
                    metadata={
                        "duration_ms": run.duration_ms,
                        "progress": 100,
                        "progress_message": "completed",
                        "output_artifacts": dict(artifacts),
                    },
                )
                await self.project_repo.update_status(
                    project.id,
                    ProjectStatus.PROCESSING.value,
                    current_stage=project.current_stage,
                )
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
                await self.stage_run_repo.mark_failed(
                    project.id,
                    stage_name.value,
                    run.error_code or ErrorCode.UNKNOWN.value,
                    run.error_message or "failed",
                    metadata={"duration_ms": run.duration_ms, "progress_message": "failed"},
                )
                await self.project_repo.update_status(
                    project.id,
                    ProjectStatus.FAILED.value,
                    current_stage=project.current_stage,
                    error_message=run.error_message,
                )
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

        if project.current_stage >= _STAGE_INDEX[StageName.LLM]:
            project.status = ProjectStatus.COMPLETED
            await self.project_repo.update_status(
                project.id,
                ProjectStatus.COMPLETED.value,
                current_stage=project.current_stage,
            )

        return project, ctx

    async def run_all(self, project: Project, from_stage: StageName | None = None) -> tuple[Project, PipelineContext]:
        if from_stage is not None:
            if from_stage not in _STAGE_INDEX:
                raise ValueError(f"Unknown stage: {from_stage}")
            project.current_stage = min(project.current_stage, _STAGE_INDEX[from_stage] - 1)
        return await self.run_stage(project, StageName.LLM)
