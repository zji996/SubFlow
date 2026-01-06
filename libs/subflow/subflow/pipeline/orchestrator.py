"""Project-based pipeline orchestrator (stage-by-stage execution)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from subflow.config import Settings
from subflow.exceptions import StageExecutionError
from subflow.models.serializers import (
    deserialize_asr_corrected_segments,
    deserialize_asr_segments,
    deserialize_semantic_chunks,
    deserialize_vad_segments,
    serialize_asr_corrected_segments,
    serialize_asr_segments,
    serialize_semantic_chunks,
    serialize_vad_segments,
)
from subflow.models.project import (
    Project,
    ProjectStatus,
    StageName,
    StageRun,
    StageRunStatus,
)
from subflow.models.segment import (
    ASRCorrectedSegment,
    ASRSegment,
    SemanticChunk,
    VADSegment,
)
from subflow.pipeline.context import PipelineContext
from subflow.stages import (
    ASRStage,
    AudioPreprocessStage,
    ExportStage,
    GlobalUnderstandingPass,
    SemanticChunkingPass,
    VADStage,
)
from subflow.storage.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


_STAGE_ORDER: list[StageName] = [
    StageName.AUDIO_PREPROCESS,
    StageName.VAD,
    StageName.ASR,
    StageName.LLM,
    StageName.EXPORT,
]

_STAGE_INDEX: dict[StageName, int] = {s: i + 1 for i, s in enumerate(_STAGE_ORDER)}


async def _maybe_close(obj: object) -> None:
    close = getattr(obj, "close", None)
    if close is None or not callable(close):
        return
    try:
        await close()
    except Exception:
        logger.exception("failed to close %r", obj)


class PipelineOrchestrator:
    """Project-first orchestrator with artifact persistence."""

    def __init__(self, settings: Settings, store: ArtifactStore):
        self.settings = settings
        self.store = store

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
                    ctx.update(stage1)
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

        if project.current_stage >= _STAGE_INDEX[StageName.LLM]:
            try:
                global_ctx = await self.store.load_json(project.id, StageName.LLM.value, "global_context.json")
                if isinstance(global_ctx, dict):
                    ctx["global_context"] = global_ctx
            except FileNotFoundError:
                pass
            try:
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
            project.stage_runs.append(run)

            try:
                logger.info("stage start (project_id=%s, stage=%s)", project.id, stage_name.value)
                if stage_name == StageName.AUDIO_PREPROCESS:
                    stage_impl = AudioPreprocessStage(self.settings)
                    try:
                        ctx = await stage_impl.execute(ctx)
                    finally:
                        await _maybe_close(stage_impl)
                    payload = {
                        "video_path": ctx.get("video_path"),
                        "audio_path": ctx.get("audio_path"),
                        "vocals_audio_path": ctx.get("vocals_audio_path"),
                    }
                    ident = await self.store.save_json(project.id, stage_name.value, "stage1.json", payload)
                    project.artifacts[stage_name.value] = {"stage1.json": ident}

                elif stage_name == StageName.VAD:
                    stage_impl = VADStage(self.settings)
                    try:
                        ctx = await stage_impl.execute(ctx)
                    finally:
                        await _maybe_close(stage_impl)
                    vad_segments: list[VADSegment] = list(ctx.get("vad_segments") or [])
                    ident = await self.store.save_json(
                        project.id,
                        stage_name.value,
                        "vad_segments.json",
                        serialize_vad_segments(vad_segments),
                    )
                    artifacts: dict[str, str] = {"vad_segments.json": ident}
                    vad_regions: list[VADSegment] = list(ctx.get("vad_regions") or [])
                    if vad_regions:
                        regions_ident = await self.store.save_json(
                            project.id,
                            stage_name.value,
                            "vad_regions.json",
                            serialize_vad_segments(vad_regions),
                        )
                        artifacts["vad_regions.json"] = regions_ident
                    project.artifacts[stage_name.value] = artifacts

                elif stage_name == StageName.ASR:
                    stage_impl = ASRStage(self.settings)
                    try:
                        ctx = await stage_impl.execute(ctx)
                    finally:
                        await _maybe_close(stage_impl)
                    asr_segments: list[ASRSegment] = list(ctx.get("asr_segments") or [])
                    asr_ident = await self.store.save_json(
                        project.id,
                        stage_name.value,
                        "asr_segments.json",
                        serialize_asr_segments(asr_segments),
                    )
                    transcript_ident = await self.store.save_text(
                        project.id, stage_name.value, "full_transcript.txt", str(ctx.get("full_transcript") or "")
                    )
                    project.artifacts[stage_name.value] = {
                        "asr_segments.json": asr_ident,
                        "full_transcript.txt": transcript_ident,
                    }

                elif stage_name == StageName.LLM:
                    max_asr = self.settings.llm.max_asr_segments
                    if isinstance(max_asr, int) and max_asr > 0:
                        asr_segments: list[ASRSegment] = list(ctx.get("asr_segments") or [])
                        if len(asr_segments) > max_asr:
                            ctx = dict(ctx)
                            ctx["asr_segments"] = asr_segments[:max_asr]
                            ctx["full_transcript"] = " ".join(
                                seg.text for seg in ctx["asr_segments"] if (seg.text or "").strip()
                            )
                            corrected = dict(ctx.get("asr_corrected_segments") or {})
                            if corrected:
                                ctx["asr_corrected_segments"] = {
                                    k: v for k, v in corrected.items() if int(k) < max_asr
                            }

                    stage1 = GlobalUnderstandingPass(self.settings)
                    try:
                        ctx = await stage1.execute(ctx)
                    finally:
                        await _maybe_close(stage1)
                    stage2 = SemanticChunkingPass(self.settings)
                    try:
                        ctx = await stage2.execute(ctx)
                    finally:
                        await _maybe_close(stage2)
                    global_ident = await self.store.save_json(
                        project.id,
                        stage_name.value,
                        "global_context.json",
                        dict(ctx.get("global_context") or {}),
                    )
                    corrected_map: dict[int, ASRCorrectedSegment] = dict(
                        ctx.get("asr_corrected_segments") or {}
                    )
                    corrected_ident = await self.store.save_json(
                        project.id,
                        stage_name.value,
                        "asr_corrected_segments.json",
                        serialize_asr_corrected_segments(corrected_map),
                    )
                    chunks: list[SemanticChunk] = list(ctx.get("semantic_chunks") or [])
                    chunks_ident = await self.store.save_json(
                        project.id,
                        stage_name.value,
                        "semantic_chunks.json",
                        serialize_semantic_chunks(chunks),
                    )
                    project.artifacts[stage_name.value] = {
                        "global_context.json": global_ident,
                        "asr_corrected_segments.json": corrected_ident,
                        "semantic_chunks.json": chunks_ident,
                    }

                elif stage_name == StageName.EXPORT:
                    stage_impl = ExportStage(self.settings, format="srt")
                    try:
                        ctx = await stage_impl.execute(ctx)
                    finally:
                        await _maybe_close(stage_impl)
                    subtitle_text = str(ctx.get("subtitle_text") or "")
                    sub_ident = await self.store.save_text(
                        project.id, stage_name.value, "subtitles.srt", subtitle_text
                    )
                    project.artifacts[stage_name.value] = {"subtitles.srt": sub_ident}

                else:  # pragma: no cover
                    raise ValueError(f"Unknown stage: {stage_name}")

                project.current_stage = idx
                run.status = StageRunStatus.COMPLETED
                run.completed_at = datetime.now(tz=timezone.utc)
                logger.info("stage done (project_id=%s, stage=%s)", project.id, stage_name.value)

            except Exception as exc:
                logger.exception("stage failed (project_id=%s, stage=%s)", project.id, stage_name.value)
                run.status = StageRunStatus.FAILED
                run.completed_at = datetime.now(tz=timezone.utc)
                run.error = str(exc)
                project.status = ProjectStatus.FAILED
                if isinstance(exc, StageExecutionError):
                    raise StageExecutionError(
                        exc.stage,
                        exc.message,
                        project_id=project.id,
                    ) from exc
                raise StageExecutionError(stage_name.value, str(exc), project_id=project.id) from exc

        if project.current_stage >= _STAGE_INDEX[StageName.EXPORT]:
            project.status = ProjectStatus.COMPLETED

        return project, ctx

    async def run_all(self, project: Project, from_stage: StageName | None = None) -> tuple[Project, PipelineContext]:
        if from_stage is not None:
            project.current_stage = min(project.current_stage, _STAGE_INDEX[from_stage] - 1)
        return await self.run_stage(project, StageName.EXPORT)
