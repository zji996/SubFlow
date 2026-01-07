"""Project-based pipeline orchestrator (stage-by-stage execution)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, cast

from subflow.config import Settings
from subflow.exceptions import StageExecutionError
from subflow.models.serializers import (
    deserialize_asr_corrected_segments,
    deserialize_asr_merged_chunks,
    deserialize_asr_segments,
    deserialize_semantic_chunks,
    deserialize_vad_segments,
    serialize_asr_corrected_segments,
    serialize_asr_merged_chunks,
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
    ASRMergedChunk,
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
    LLMASRCorrectionStage,
    SemanticChunkingPass,
    VADStage,
)
from subflow.storage.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


_STAGE_ORDER: list[StageName] = [
    StageName.AUDIO_PREPROCESS,
    StageName.VAD,
    StageName.ASR,
    StageName.LLM_ASR_CORRECTION,
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

    def __init__(self, settings: Settings, store: ArtifactStore) -> None:
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
            project.stage_runs.append(run)

            try:
                logger.info("stage start (project_id=%s, stage=%s)", project.id, stage_name.value)
                if stage_name == StageName.AUDIO_PREPROCESS:
                    audio_stage = AudioPreprocessStage(self.settings)
                    try:
                        ctx = await audio_stage.execute(ctx)
                    finally:
                        await _maybe_close(audio_stage)
                    payload = {
                        "video_path": ctx.get("video_path"),
                        "audio_path": ctx.get("audio_path"),
                        "vocals_audio_path": ctx.get("vocals_audio_path"),
                    }
                    ident = await self.store.save_json(project.id, stage_name.value, "stage1.json", payload)
                    project.artifacts[stage_name.value] = {"stage1.json": ident}

                elif stage_name == StageName.VAD:
                    vad_stage = VADStage(self.settings)
                    try:
                        ctx = await vad_stage.execute(ctx)
                    finally:
                        await _maybe_close(vad_stage)
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
                    asr_stage = ASRStage(self.settings)
                    try:
                        ctx = await asr_stage.execute(ctx)
                    finally:
                        await _maybe_close(asr_stage)
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
                    merged_chunks: list[ASRMergedChunk] = list(ctx.get("asr_merged_chunks") or [])
                    merged_ident = await self.store.save_json(
                        project.id,
                        stage_name.value,
                        "asr_merged_chunks.json",
                        serialize_asr_merged_chunks(merged_chunks),
                    )
                    project.artifacts[stage_name.value] = {
                        "asr_segments.json": asr_ident,
                        "full_transcript.txt": transcript_ident,
                        "asr_merged_chunks.json": merged_ident,
                    }

                elif stage_name == StageName.LLM_ASR_CORRECTION:
                    correction_stage = LLMASRCorrectionStage(self.settings)
                    try:
                        ctx = await correction_stage.execute(ctx)
                    finally:
                        await _maybe_close(correction_stage)

                    corrected_map: dict[int, ASRCorrectedSegment] = dict(ctx.get("asr_corrected_segments") or {})
                    corrected_ident = await self.store.save_json(
                        project.id,
                        stage_name.value,
                        "asr_corrected_segments.json",
                        serialize_asr_corrected_segments(corrected_map),
                    )
                    project.artifacts[stage_name.value] = {
                        "asr_corrected_segments.json": corrected_ident,
                    }

                elif stage_name == StageName.LLM:
                    max_asr = self.settings.llm_limits.max_asr_segments
                    if isinstance(max_asr, int) and max_asr > 0:
                        asr_segments_for_llm: list[ASRSegment] = list(ctx.get("asr_segments") or [])
                        if len(asr_segments_for_llm) > max_asr:
                            ctx = cast(PipelineContext, dict(ctx))
                            ctx["asr_segments"] = asr_segments_for_llm[:max_asr]
                            ctx["full_transcript"] = " ".join(
                                seg.text for seg in ctx["asr_segments"] if (seg.text or "").strip()
                            )
                            corrected = dict(ctx.get("asr_corrected_segments") or {})
                            if corrected:
                                filtered: dict[int, ASRCorrectedSegment] = {}
                                for k, v in corrected.items():
                                    try:
                                        key = int(k)
                                    except (TypeError, ValueError):
                                        continue
                                    if key < max_asr and isinstance(v, ASRCorrectedSegment):
                                        filtered[key] = v
                                if filtered:
                                    ctx["asr_corrected_segments"] = filtered

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
                    chunks: list[SemanticChunk] = list(ctx.get("semantic_chunks") or [])
                    chunks_ident = await self.store.save_json(
                        project.id,
                        stage_name.value,
                        "semantic_chunks.json",
                        serialize_semantic_chunks(chunks),
                    )
                    project.artifacts[stage_name.value] = {
                        "global_context.json": global_ident,
                        "semantic_chunks.json": chunks_ident,
                    }

                elif stage_name == StageName.EXPORT:
                    export_stage = ExportStage(self.settings, format="srt")
                    try:
                        ctx = await export_stage.execute(ctx)
                    finally:
                        await _maybe_close(export_stage)
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
