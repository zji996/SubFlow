"""ASR stage with real GLM-ASR provider integration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import cast

from subflow.config import Settings
from subflow.models.segment import ASRMergedChunk, ASRSegment, VADSegment
from subflow.pipeline.context import PipelineContext, ProgressReporter
from subflow.providers import get_asr_provider
from subflow.stages.base import Stage
from subflow.utils.audio import cleanup_segment_files, cut_audio_segments_batch
from subflow.utils.audio_chunk_merger import (
    build_merged_chunk_specs,
    cut_merged_chunk_audio,
)

logger = logging.getLogger(__name__)


class ASRStage(Stage):
    """ASR stage that transcribes VAD segments using GLM-ASR."""

    name = "asr"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        cfg = settings.asr.model_dump()
        cfg["max_concurrent"] = max(1, int(settings.concurrency_asr))
        self.provider = get_asr_provider(cfg)

    def validate_input(self, context: PipelineContext) -> bool:
        """Check that vocals audio and VAD segments exist."""
        return bool(context.get("vocals_audio_path")) and bool(context.get("vad_segments"))

    async def execute(
        self,
        context: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> PipelineContext:
        """Execute ASR on all VAD segments concurrently.

        Input context keys:
            - vocals_audio_path: Path to the vocals audio file
            - vad_segments: List of VADSegment objects

        Output context keys (added):
            - asr_segments: List of ASRSegment objects
            - full_transcript: Complete transcript text
            - source_language: Detected or specified source language
        """
        context = cast(PipelineContext, dict(context))
        vocals_path: str = context["vocals_audio_path"]
        vad_segments: list[VADSegment] = context["vad_segments"]
        vad_regions: list[VADSegment] = list(context.get("vad_regions") or [])
        source_language = context.get("source_language") or None
        max_concurrent = max(1, int(self.settings.concurrency_asr))

        if not vad_segments:
            logger.info("asr skipped (no vad_segments)")
            context["asr_segments"] = []
            context["full_transcript"] = ""
            return context

        merged_specs = build_merged_chunk_specs(
            vad_regions,
            vad_segments,
            max_chunk_s=float(self.settings.asr.max_chunk_s),
        )

        # Create workdir for audio segments / merged chunks (cleaned up after stage)
        run_id = str(context.get("project_id") or context.get("job_id") or "unknown")
        base_dir = Path(self.settings.data_dir) / "workdir" / run_id
        segments_dir = base_dir / "asr_segments"
        merged_dir = base_dir / "asr_merged_chunks"

        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            logger.info("asr start (segments=%d)", len(vad_segments))
            # 1. Cut audio into segments (concurrent ffmpeg)
            time_ranges = [(seg.start, seg.end) for seg in vad_segments]
            segment_paths = await cut_audio_segments_batch(
                input_path=vocals_path,
                segments=time_ranges,
                output_dir=str(segments_dir),
                max_concurrent=int(self.settings.asr.ffmpeg_concurrency),
                ffmpeg_bin=self.settings.audio.ffmpeg_bin,
            )

            total_tasks = len(segment_paths) + len(merged_specs)
            progress_done = 0
            progress_lock = asyncio.Lock()

            async def _report_progress(*, done: int, total: int, message: str) -> None:
                if not progress_reporter or total <= 0:
                    return
                pct = int(done / total * 100)
                await progress_reporter.report(pct, message)

            await _report_progress(
                done=0,
                total=total_tasks,
                message=f"ASR 识别中 0/{max(1, total_tasks)}",
            )

            # 2. Transcribe all segments concurrently
            semaphore = asyncio.Semaphore(max_concurrent)

            async def _transcribe_one(path: str) -> str:
                async with semaphore:
                    try:
                        segs = await self.provider.transcribe(path, language=source_language)
                        return segs[0].text if segs else ""
                    except Exception as exc:
                        logger.warning("asr error for %s: %s", path, exc)
                        return ""

            texts: list[str] = [""] * len(segment_paths)

            async def _run_segment(i: int, path: str) -> None:
                nonlocal progress_done
                text = await _transcribe_one(path)
                texts[i] = text
                async with progress_lock:
                    progress_done += 1
                    await _report_progress(
                        done=progress_done,
                        total=total_tasks,
                        message=f"ASR 识别中 {progress_done}/{max(1, total_tasks)}",
                    )

            await asyncio.gather(*[_run_segment(i, p) for i, p in enumerate(segment_paths)])

            # 3. Assemble results with timing
            asr_segments: list[ASRSegment] = []
            for i, (vad_seg, text) in enumerate(zip(vad_segments, texts)):
                asr_segments.append(
                    ASRSegment(
                        id=i,
                        start=vad_seg.start,
                        end=vad_seg.end,
                        text=text.strip(),
                        language=source_language,
                    )
                )

            # 4. Build full transcript
            full_transcript = " ".join(seg.text for seg in asr_segments if seg.text)

            context["asr_segments"] = asr_segments
            context["full_transcript"] = full_transcript
            context["source_language"] = source_language

            # 5. Region-merged ASR (<=30s chunks per region)
            merged_chunks: list[ASRMergedChunk] = []
            if merged_specs:
                logger.info(
                    "asr merged_chunks build (chunks=%d, total_audio_s=%.2f)",
                    len(merged_specs),
                    sum(float(x.duration_s) for x in merged_specs),
                )
                merged_paths = await cut_merged_chunk_audio(
                    vocals_path,
                    merged_specs,
                    output_dir=str(merged_dir),
                    ffmpeg_bin=self.settings.audio.ffmpeg_bin,
                    max_concurrent=4,
                )
                merged_texts: list[str] = [""] * len(merged_paths)

                async def _run_merged(i: int, path: str) -> None:
                    nonlocal progress_done
                    text = await _transcribe_one(path)
                    merged_texts[i] = text
                    async with progress_lock:
                        progress_done += 1
                        await _report_progress(
                            done=progress_done,
                            total=total_tasks,
                            message=f"ASR 识别中 {progress_done}/{max(1, total_tasks)}",
                        )

                await asyncio.gather(*[_run_merged(i, p) for i, p in enumerate(merged_paths)])
                for spec, text in zip(merged_specs, merged_texts):
                    merged_chunks.append(
                        ASRMergedChunk(
                            region_id=int(spec.region_id),
                            chunk_id=int(spec.chunk_id),
                            start=float(spec.start),
                            end=float(spec.end),
                            segment_ids=[int(x) for x in spec.segment_ids],
                            text=str(text or "").strip(),
                        )
                    )
            context["asr_merged_chunks"] = merged_chunks
            logger.info(
                "asr done (asr_segments=%d, merged_chunks=%d)",
                len(asr_segments),
                len(merged_chunks),
            )

        finally:
            # Cleanup temporary audio files
            if segments_dir.exists():
                cleanup_segment_files([str(p) for p in segments_dir.glob("*.wav")])
                try:
                    segments_dir.rmdir()
                except OSError as exc:
                    logger.debug("failed to remove temp dir %s: %s", segments_dir, exc)
            if merged_dir.exists():
                cleanup_segment_files([str(p) for p in merged_dir.glob("*.wav")])
                try:
                    merged_dir.rmdir()
                except OSError as exc:
                    logger.debug("failed to remove temp dir %s: %s", merged_dir, exc)
            if base_dir.exists():
                try:
                    base_dir.rmdir()
                except OSError:
                    # Keep workdir when other stages wrote additional temp files.
                    pass

        return context

    async def close(self) -> None:
        """Release provider resources."""
        await self.provider.close()
