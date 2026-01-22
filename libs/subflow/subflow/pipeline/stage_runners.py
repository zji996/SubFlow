"""Stage runners for PipelineOrchestrator (execute + persist)."""

from __future__ import annotations

import logging
import time
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
from subflow.pipeline.context import (
    MetricsProgressReporter,
    PipelineContext,
    ProgressReporter,
    StageMetrics,
)
from subflow.repositories import (
    ASRMergedChunkRepository,
    ASRSegmentRepository,
    GlobalContextRepository,
    ProjectRepository,
    SemanticChunkRepository,
    VADRegionRepository,
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
from subflow.utils.vad_frame_probs_io import encode_vad_frame_probs

logger = logging.getLogger(__name__)


class _LLMStageProgressReporter(ProgressReporter):
    def __init__(self, inner: ProgressReporter) -> None:
        self._inner = inner
        self._started_at = time.monotonic()
        self._range_start = 0
        self._range_end = 100
        self._llm_prompt_offset = 0
        self._llm_completion_offset = 0
        self._llm_calls_offset = 0
        self._llm_prompt_total = 0
        self._llm_completion_total = 0
        self._llm_calls_total = 0

    def set_phase_range(self, start_pct: int, end_pct: int) -> None:
        start = max(0, min(100, int(start_pct)))
        end = max(0, min(100, int(end_pct)))
        if end < start:
            start, end = end, start
        self._range_start = start
        self._range_end = end

    def advance_llm_offsets(self) -> None:
        self._llm_prompt_offset = int(self._llm_prompt_total)
        self._llm_completion_offset = int(self._llm_completion_total)
        self._llm_calls_offset = int(self._llm_calls_total)

    def _map_progress(self, pct: int) -> int:
        p = max(0, min(100, int(pct)))
        span = self._range_end - self._range_start
        return int(self._range_start + (p / 100.0) * span)

    async def report(self, progress: int, message: str) -> None:
        await self._inner.report(self._map_progress(progress), message)

    async def report_metrics(self, metrics: StageMetrics) -> None:
        payload = dict(metrics or {})
        raw_progress = payload.get("progress")
        if isinstance(raw_progress, int):
            payload["progress"] = self._map_progress(raw_progress)

        saw_tokens = False
        raw_prompt = payload.get("llm_prompt_tokens")
        if isinstance(raw_prompt, int):
            self._llm_prompt_total = int(self._llm_prompt_offset + raw_prompt)
            payload["llm_prompt_tokens"] = int(self._llm_prompt_total)
            saw_tokens = True

        raw_completion = payload.get("llm_completion_tokens")
        if isinstance(raw_completion, int):
            self._llm_completion_total = int(self._llm_completion_offset + raw_completion)
            payload["llm_completion_tokens"] = int(self._llm_completion_total)
            saw_tokens = True

        if saw_tokens:
            elapsed = max(0.001, time.monotonic() - self._started_at)
            total_tokens = int(self._llm_prompt_total) + int(self._llm_completion_total)
            payload["llm_tokens_per_second"] = float(total_tokens) / elapsed

        raw_calls = payload.get("llm_calls_count")
        if isinstance(raw_calls, int):
            self._llm_calls_total = int(self._llm_calls_offset + raw_calls)
            payload["llm_calls_count"] = int(self._llm_calls_total)

        if isinstance(self._inner, MetricsProgressReporter):
            await self._inner.report_metrics(payload)
            return

        progress = payload.get("progress")
        message = payload.get("progress_message") or payload.get("message")
        if isinstance(progress, int):
            await self._inner.report(progress, str(message or "running"))


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
        project_repo: ProjectRepository,
        vad_repo: VADRegionRepository,
        asr_repo: ASRSegmentRepository,
        asr_merged_chunk_repo: ASRMergedChunkRepository,
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
        store: ArtifactStore,  # noqa: ARG002
        project_repo: ProjectRepository,
        vad_repo: VADRegionRepository,  # noqa: ARG002
        asr_repo: ASRSegmentRepository,  # noqa: ARG002
        asr_merged_chunk_repo: ASRMergedChunkRepository,  # noqa: ARG002
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

        def _blob_hash_from_path(value: object) -> str | None:
            p = str(value or "").strip()
            if not p:
                return None
            name = p.rsplit("/", 1)[-1]
            if len(name) == 64:
                lower = name.lower()
                if all(ch in "0123456789abcdef" for ch in lower):
                    return lower
            return None

        media_files: dict[str, object] = {}
        video_path = payload.get("video_path")
        audio_path = payload.get("audio_path")
        vocals_path = payload.get("vocals_audio_path")
        if video_path:
            media_files["video"] = {
                "blob_sha256": _blob_hash_from_path(video_path),
                "path": str(video_path),
            }
        if audio_path:
            media_files["audio"] = {
                "blob_sha256": _blob_hash_from_path(audio_path),
                "path": str(audio_path),
            }
        if vocals_path:
            media_files["vocals"] = {
                "blob_sha256": _blob_hash_from_path(vocals_path),
                "path": str(vocals_path),
            }
        if media_files:
            await project_repo.update_media_files(project.id, media_files)
            project.media_files = dict(media_files)

        return ctx, {}


class VADRunner(StageRunner):
    stage_name = StageName.VAD

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,
        project_repo: ProjectRepository,  # noqa: ARG002
        vad_repo: VADRegionRepository,
        asr_repo: ASRSegmentRepository,  # noqa: ARG002
        asr_merged_chunk_repo: ASRMergedChunkRepository,  # noqa: ARG002
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
        vad_regions: list[VADSegment] = list(ctx.get("vad_regions") or ctx.get("vad_segments") or [])
        if "vad_regions" not in ctx and ctx.get("vad_segments"):
            ctx["vad_regions"] = list(ctx.get("vad_segments") or [])
        ctx.pop("vad_segments", None)

        for i, region in enumerate(vad_regions):
            if region.region_id is None:
                region.region_id = int(i)
        await vad_repo.bulk_insert(project.id, vad_regions)

        artifacts: dict[str, str] = {}
        frame_probs = ctx.get("vad_frame_probs")
        hop_s = float(ctx.get("vad_frame_hop_s") or 0.0)
        if frame_probs is not None and hop_s > 0:
            ident = await store.save(
                project.id,
                self.stage_name.value,
                "vad_frame_probs.bin",
                encode_vad_frame_probs(frame_probs=frame_probs, frame_hop_s=hop_s),
            )
            artifacts["vad_frame_probs.bin"] = ident
        return ctx, artifacts


class ASRRunner(StageRunner):
    stage_name = StageName.ASR

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,  # noqa: ARG002
        project_repo: ProjectRepository,  # noqa: ARG002
        vad_repo: VADRegionRepository,  # noqa: ARG002
        asr_repo: ASRSegmentRepository,
        asr_merged_chunk_repo: ASRMergedChunkRepository,
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
        await asr_merged_chunk_repo.delete_by_project(project.id)
        if merged_chunks:
            await asr_merged_chunk_repo.bulk_upsert(project.id, merged_chunks)
        return ctx, {}


class LLMASRCorrectionRunner(StageRunner):
    stage_name = StageName.LLM_ASR_CORRECTION

    async def run(
        self,
        *,
        settings: Settings,
        store: ArtifactStore,  # noqa: ARG002
        project_repo: ProjectRepository,  # noqa: ARG002
        vad_repo: VADRegionRepository,  # noqa: ARG002
        asr_repo: ASRSegmentRepository,
        asr_merged_chunk_repo: ASRMergedChunkRepository,  # noqa: ARG002
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

        corrected_map: dict[int, ASRCorrectedSegment] = dict(
            ctx.get("asr_corrected_segments") or {}
        )
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
        store: ArtifactStore,  # noqa: ARG002
        project_repo: ProjectRepository,  # noqa: ARG002
        vad_repo: VADRegionRepository,  # noqa: ARG002
        asr_repo: ASRSegmentRepository,  # noqa: ARG002
        asr_merged_chunk_repo: ASRMergedChunkRepository,  # noqa: ARG002
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

        llm_reporter: ProgressReporter | None
        if progress_reporter is not None:
            llm_reporter = _LLMStageProgressReporter(progress_reporter)
            cast(_LLMStageProgressReporter, llm_reporter).set_phase_range(0, 20)
        else:
            llm_reporter = None

        stage1 = GlobalUnderstandingPass(settings)
        try:
            ctx = await stage1.execute(ctx, llm_reporter)
        finally:
            await _maybe_close(stage1)

        if isinstance(llm_reporter, _LLMStageProgressReporter):
            llm_reporter.advance_llm_offsets()
            llm_reporter.set_phase_range(20, 100)

        stage2 = SemanticChunkingPass(settings)
        try:
            ctx = await stage2.execute(ctx, llm_reporter)
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
