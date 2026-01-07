"""ASR stage with real GLM-ASR provider integration."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import cast

from subflow.config import Settings
from subflow.models.segment import ASRMergedChunk, ASRSegment, VADSegment
from subflow.pipeline.context import PipelineContext
from subflow.providers.asr.glm_asr import GLMASRProvider
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
        max_concurrent = max(1, int(settings.concurrency_asr))
        self.provider = GLMASRProvider(
            base_url=settings.asr.base_url,
            model=settings.asr.model,
            api_key=settings.asr.api_key or "abc123",
            max_concurrent=max_concurrent,
            timeout=settings.asr.timeout,
        )

    def validate_input(self, context: PipelineContext) -> bool:
        """Check that vocals audio and VAD segments exist."""
        return bool(context.get("vocals_audio_path")) and bool(context.get("vad_segments"))

    async def execute(self, context: PipelineContext) -> PipelineContext:
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

        # Create temp directory for audio segments / merged chunks
        run_id = str(context.get("project_id") or context.get("job_id") or "unknown")
        base_dir = Path(tempfile.gettempdir()) / "subflow" / run_id
        segments_dir = base_dir / "asr_segments"
        merged_dir = base_dir / "asr_merged_chunks"

        try:
            logger.info("asr start (segments=%d)", len(vad_segments))
            # 1. Cut audio into segments (concurrent ffmpeg)
            time_ranges = [(seg.start, seg.end) for seg in vad_segments]
            segment_paths = await cut_audio_segments_batch(
                input_path=vocals_path,
                segments=time_ranges,
                output_dir=str(segments_dir),
                max_concurrent=10,  # FFmpeg 并发数
                ffmpeg_bin=self.settings.audio.ffmpeg_bin,
            )

            # 2. Transcribe all segments concurrently
            import asyncio

            semaphore = asyncio.Semaphore(max_concurrent)

            async def _one(path: str) -> str:
                async with semaphore:
                    try:
                        segs = await self.provider.transcribe(path, language=source_language)
                        return segs[0].text if segs else ""
                    except Exception as exc:
                        logger.warning("asr error for %s: %s", path, exc)
                        return ""

            texts = list(await asyncio.gather(*[_one(p) for p in segment_paths]))

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
            merged_specs = build_merged_chunk_specs(
                vad_regions,
                vad_segments,
                max_chunk_s=30.0,
            )
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
                merged_texts = list(await asyncio.gather(*[_one(p) for p in merged_paths]))
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
                except OSError:
                    pass
            if merged_dir.exists():
                cleanup_segment_files([str(p) for p in merged_dir.glob("*.wav")])
                try:
                    merged_dir.rmdir()
                except OSError:
                    pass

        return context

    async def close(self) -> None:
        """Release provider resources."""
        await self.provider.close()
