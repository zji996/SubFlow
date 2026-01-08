"""Stage runners for PipelineOrchestrator (execute + persist)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import cast

from subflow.config import Settings
from subflow.models.serializers import (
    serialize_asr_corrected_segments,
    serialize_asr_merged_chunks,
    serialize_asr_segments,
    serialize_semantic_chunks,
    serialize_vad_segments,
)
from subflow.models.project import Project, StageName
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


async def _maybe_close(obj: object) -> None:
    close = getattr(obj, "close", None)
    if close is None or not callable(close):
        return
    try:
        await close()
    except Exception:
        logger.exception("failed to close %r", obj)


class StageRunner(ABC):
    stage_name: StageName

    @abstractmethod
    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        project: Project,
        ctx: PipelineContext,
    ) -> tuple[PipelineContext, dict[str, str]]:
        raise NotImplementedError


class AudioPreprocessRunner(StageRunner):
    stage_name = StageName.AUDIO_PREPROCESS

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        project: Project,
        ctx: PipelineContext,
    ) -> tuple[PipelineContext, dict[str, str]]:
        stage = AudioPreprocessStage(settings)
        try:
            ctx = await stage.execute(ctx)
        finally:
            await _maybe_close(stage)

        payload = {
            "video_path": ctx.get("video_path"),
            "audio_path": ctx.get("audio_path"),
            "vocals_audio_path": ctx.get("vocals_audio_path"),
        }
        ident = await store.save_json(project.id, self.stage_name.value, "stage1.json", payload)
        return ctx, {"stage1.json": ident}


class VADRunner(StageRunner):
    stage_name = StageName.VAD

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        project: Project,
        ctx: PipelineContext,
    ) -> tuple[PipelineContext, dict[str, str]]:
        stage = VADStage(settings)
        try:
            ctx = await stage.execute(ctx)
        finally:
            await _maybe_close(stage)

        vad_segments: list[VADSegment] = list(ctx.get("vad_segments") or [])
        ident = await store.save_json(
            project.id,
            self.stage_name.value,
            "vad_segments.json",
            serialize_vad_segments(vad_segments),
        )
        artifacts: dict[str, str] = {"vad_segments.json": ident}

        vad_regions: list[VADSegment] = list(ctx.get("vad_regions") or [])
        if vad_regions:
            regions_ident = await store.save_json(
                project.id,
                self.stage_name.value,
                "vad_regions.json",
                serialize_vad_segments(vad_regions),
            )
            artifacts["vad_regions.json"] = regions_ident

        return ctx, artifacts


class ASRRunner(StageRunner):
    stage_name = StageName.ASR

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        project: Project,
        ctx: PipelineContext,
    ) -> tuple[PipelineContext, dict[str, str]]:
        stage = ASRStage(settings)
        try:
            ctx = await stage.execute(ctx)
        finally:
            await _maybe_close(stage)

        asr_segments: list[ASRSegment] = list(ctx.get("asr_segments") or [])
        asr_ident = await store.save_json(
            project.id,
            self.stage_name.value,
            "asr_segments.json",
            serialize_asr_segments(asr_segments),
        )
        transcript_ident = await store.save_text(
            project.id,
            self.stage_name.value,
            "full_transcript.txt",
            str(ctx.get("full_transcript") or ""),
        )
        merged_chunks: list[ASRMergedChunk] = list(ctx.get("asr_merged_chunks") or [])
        merged_ident = await store.save_json(
            project.id,
            self.stage_name.value,
            "asr_merged_chunks.json",
            serialize_asr_merged_chunks(merged_chunks),
        )
        return ctx, {
            "asr_segments.json": asr_ident,
            "full_transcript.txt": transcript_ident,
            "asr_merged_chunks.json": merged_ident,
        }


class LLMASRCorrectionRunner(StageRunner):
    stage_name = StageName.LLM_ASR_CORRECTION

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        project: Project,
        ctx: PipelineContext,
    ) -> tuple[PipelineContext, dict[str, str]]:
        stage = LLMASRCorrectionStage(settings)
        try:
            ctx = await stage.execute(ctx)
        finally:
            await _maybe_close(stage)

        corrected_map: dict[int, ASRCorrectedSegment] = dict(ctx.get("asr_corrected_segments") or {})
        corrected_ident = await store.save_json(
            project.id,
            self.stage_name.value,
            "asr_corrected_segments.json",
            serialize_asr_corrected_segments(corrected_map),
        )
        return ctx, {"asr_corrected_segments.json": corrected_ident}


class LLMRunner(StageRunner):
    stage_name = StageName.LLM

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        project: Project,
        ctx: PipelineContext,
    ) -> tuple[PipelineContext, dict[str, str]]:
        max_asr = settings.llm_limits.max_asr_segments
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

        stage1 = GlobalUnderstandingPass(settings)
        try:
            ctx = await stage1.execute(ctx)
        finally:
            await _maybe_close(stage1)

        stage2 = SemanticChunkingPass(settings)
        try:
            ctx = await stage2.execute(ctx)
        finally:
            await _maybe_close(stage2)

        global_ident = await store.save_json(
            project.id,
            self.stage_name.value,
            "global_context.json",
            dict(ctx.get("global_context") or {}),
        )
        chunks: list[SemanticChunk] = list(ctx.get("semantic_chunks") or [])
        chunks_ident = await store.save_json(
            project.id,
            self.stage_name.value,
            "semantic_chunks.json",
            serialize_semantic_chunks(chunks),
        )
        return ctx, {"global_context.json": global_ident, "semantic_chunks.json": chunks_ident}


class ExportRunner(StageRunner):
    stage_name = StageName.EXPORT

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        project: Project,
        ctx: PipelineContext,
    ) -> tuple[PipelineContext, dict[str, str]]:
        stage = ExportStage(settings, format="srt")
        try:
            ctx = await stage.execute(ctx)
        finally:
            await _maybe_close(stage)

        subtitle_text = str(ctx.get("subtitle_text") or "")
        sub_ident = await store.save_text(project.id, self.stage_name.value, "subtitles.srt", subtitle_text)
        return ctx, {"subtitles.srt": sub_ident}


RUNNERS: dict[StageName, StageRunner] = {
    StageName.AUDIO_PREPROCESS: AudioPreprocessRunner(),
    StageName.VAD: VADRunner(),
    StageName.ASR: ASRRunner(),
    StageName.LLM_ASR_CORRECTION: LLMASRCorrectionRunner(),
    StageName.LLM: LLMRunner(),
    StageName.EXPORT: ExportRunner(),
}

