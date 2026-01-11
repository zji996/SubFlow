"""Stage runners for PipelineOrchestrator (execute + persist)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import cast

from subflow.config import Settings
from subflow.models.project import Project, StageName
from subflow.models.segment import (
    ASRCorrectedSegment,
    ASRMergedChunk,
    ASRSegment,
    SemanticChunk,
    VADSegment,
)
from subflow.pipeline.context import PipelineContext, ProgressReporter
from subflow.repositories import (
    ASRSegmentRepository,
    GlobalContextRepository,
    SemanticChunkRepository,
    VADSegmentRepository,
)
from subflow.stages import (
    ASRStage,
    AudioPreprocessStage,
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
        vad_repo: VADSegmentRepository,
        asr_repo: ASRSegmentRepository,
        global_context_repo: GlobalContextRepository,
        semantic_chunk_repo: SemanticChunkRepository,
        project: Project,
        ctx: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> tuple[PipelineContext, dict[str, str]]:
        raise NotImplementedError


class AudioPreprocessRunner(StageRunner):
    stage_name = StageName.AUDIO_PREPROCESS

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        vad_repo: VADSegmentRepository,  # noqa: ARG002
        asr_repo: ASRSegmentRepository,  # noqa: ARG002
        global_context_repo: GlobalContextRepository,  # noqa: ARG002
        semantic_chunk_repo: SemanticChunkRepository,  # noqa: ARG002
        project: Project,
        ctx: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> tuple[PipelineContext, dict[str, str]]:
        stage = AudioPreprocessStage(settings)
        try:
            ctx = await stage.execute(ctx, progress_reporter)
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
        vad_repo: VADSegmentRepository,
        asr_repo: ASRSegmentRepository,  # noqa: ARG002
        global_context_repo: GlobalContextRepository,  # noqa: ARG002
        semantic_chunk_repo: SemanticChunkRepository,  # noqa: ARG002
        project: Project,
        ctx: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> tuple[PipelineContext, dict[str, str]]:
        stage = VADStage(settings)
        try:
            ctx = await stage.execute(ctx, progress_reporter)
        finally:
            await _maybe_close(stage)

        await vad_repo.delete_by_project(project.id)
        vad_segments: list[VADSegment] = list(ctx.get("vad_segments") or [])
        await vad_repo.bulk_insert(project.id, vad_segments)
        return ctx, {}


class ASRRunner(StageRunner):
    stage_name = StageName.ASR

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        vad_repo: VADSegmentRepository,  # noqa: ARG002
        asr_repo: ASRSegmentRepository,
        global_context_repo: GlobalContextRepository,  # noqa: ARG002
        semantic_chunk_repo: SemanticChunkRepository,  # noqa: ARG002
        project: Project,
        ctx: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> tuple[PipelineContext, dict[str, str]]:
        stage = ASRStage(settings)
        try:
            ctx = await stage.execute(ctx, progress_reporter)
        finally:
            await _maybe_close(stage)

        await asr_repo.delete_by_project(project.id)
        asr_segments: list[ASRSegment] = list(ctx.get("asr_segments") or [])
        await asr_repo.bulk_insert(project.id, asr_segments)

        merged_chunks: list[ASRMergedChunk] = list(ctx.get("asr_merged_chunks") or [])
        merged_ident = ""
        if merged_chunks:
            from subflow.models.serializers import serialize_asr_merged_chunks

            merged_ident = await store.save_json(
                project.id,
                self.stage_name.value,
                "asr_merged_chunks.json",
                serialize_asr_merged_chunks(merged_chunks),
            )
        artifacts: dict[str, str] = {}
        if merged_ident:
            artifacts["asr_merged_chunks.json"] = merged_ident
        return ctx, {
            **artifacts,
        }


class LLMASRCorrectionRunner(StageRunner):
    stage_name = StageName.LLM_ASR_CORRECTION

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        vad_repo: VADSegmentRepository,  # noqa: ARG002
        asr_repo: ASRSegmentRepository,
        global_context_repo: GlobalContextRepository,  # noqa: ARG002
        semantic_chunk_repo: SemanticChunkRepository,  # noqa: ARG002
        project: Project,
        ctx: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> tuple[PipelineContext, dict[str, str]]:
        stage = LLMASRCorrectionStage(settings)
        try:
            ctx = await stage.execute(ctx, progress_reporter)
        finally:
            await _maybe_close(stage)

        corrected_map: dict[int, ASRCorrectedSegment] = dict(ctx.get("asr_corrected_segments") or {})
        await asr_repo.update_corrected_texts(
            project.id,
            {int(k): str(v.text or "") for k, v in corrected_map.items()},
        )
        return ctx, {}


class LLMRunner(StageRunner):
    stage_name = StageName.LLM

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        vad_repo: VADSegmentRepository,  # noqa: ARG002
        asr_repo: ASRSegmentRepository,  # noqa: ARG002
        global_context_repo: GlobalContextRepository,
        semantic_chunk_repo: SemanticChunkRepository,
        project: Project,
        ctx: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> tuple[PipelineContext, dict[str, str]]:
        await global_context_repo.delete(project.id)
        await semantic_chunk_repo.delete_by_project(project.id)

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
            ctx = await stage1.execute(ctx, progress_reporter)
        finally:
            await _maybe_close(stage1)

        stage2 = SemanticChunkingPass(settings)
        try:
            ctx = await stage2.execute(ctx, progress_reporter)
        finally:
            await _maybe_close(stage2)

        await global_context_repo.save(project.id, dict(ctx.get("global_context") or {}))
        chunks: list[SemanticChunk] = list(ctx.get("semantic_chunks") or [])
        await semantic_chunk_repo.bulk_insert(project.id, chunks)
        return ctx, {}


RUNNERS: dict[StageName, StageRunner] = {
    StageName.AUDIO_PREPROCESS: AudioPreprocessRunner(),
    StageName.VAD: VADRunner(),
    StageName.ASR: ASRRunner(),
    StageName.LLM_ASR_CORRECTION: LLMASRCorrectionRunner(),
    StageName.LLM: LLMRunner(),
}
