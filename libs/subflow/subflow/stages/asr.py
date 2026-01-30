"""ASR stage (greedy sentence-aligned ASR)."""

from __future__ import annotations

import asyncio
import logging
import time
from itertools import count
from pathlib import Path
from typing import cast

from subflow.config import Settings
from subflow.exceptions import StageExecutionError
from subflow.models.segment import ASRMergedChunk, ASRSegment, SentenceSegment, VADSegment
from subflow.pipeline.concurrency import get_concurrency_tracker
from subflow.pipeline.context import MetricsProgressReporter, PipelineContext, ProgressReporter
from subflow.providers import get_asr_provider
from subflow.stages.base import Stage
from subflow.utils.audio import cleanup_segment_files, cut_audio_segment, cut_audio_segments_batch
from subflow.utils.audio_chunk_merger import (
    build_merged_chunk_specs,
    cut_merged_chunk_audio,
)
from subflow.utils.greedy_sentence_aligner import (
    GreedySentenceAlignerConfig,
    greedy_sentence_align_region,
)
from subflow.utils.vad_region_partition import partition_vad_regions_by_gap

logger = logging.getLogger(__name__)


class ASRStage(Stage):
    """Stage 3: Greedy sentence-aligned ASR.

    Inputs:
      - vocals_audio_path
      - vad_regions (or vad_segments as fallback)
      - vad_frame_probs + vad_frame_hop_s (required for greedy alignment)

    Outputs:
      - sentence_segments
      - asr_segments
      - asr_merged_chunks
      - full_transcript
    """

    name = "asr"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        cfg = settings.asr.model_dump()
        cfg["max_concurrent"] = max(1, int(settings.concurrency_asr))
        self.provider = get_asr_provider(cfg)

    def validate_input(self, context: PipelineContext) -> bool:
        return bool(context.get("vocals_audio_path")) and bool(
            context.get("vad_regions") or context.get("vad_segments")
        )

    async def execute(
        self,
        context: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> PipelineContext:
        context = cast(PipelineContext, dict(context))
        vocals_path: str = context["vocals_audio_path"]
        vad_regions: list[VADSegment] = list(
            context.get("vad_regions") or context.get("vad_segments") or []
        )
        source_language = context.get("source_language") or None
        tracker = get_concurrency_tracker(self.settings)

        if not vad_regions:
            logger.info("asr skipped (no vad_regions)")
            context["sentence_segments"] = []
            context["asr_segments"] = []
            context["asr_merged_chunks"] = []
            context["full_transcript"] = ""
            return context

        vad_frame_probs = context.get("vad_frame_probs")
        frame_hop_s = float(context.get("vad_frame_hop_s") or 0.0)
        if vad_frame_probs is None or frame_hop_s <= 0:
            raise StageExecutionError(
                self.name,
                "Missing vad_frame_probs/vad_frame_hop_s; run VAD stage before ASR stage",
            )
        greedy_cfg = GreedySentenceAlignerConfig(
            max_chunk_s=float(self.settings.greedy_sentence_asr.max_chunk_s),
            fallback_chunk_s=float(self.settings.greedy_sentence_asr.fallback_chunk_s),
            max_segment_s=float(self.settings.greedy_sentence_asr.max_segment_s),
            max_segment_chars=int(self.settings.greedy_sentence_asr.max_segment_chars),
            vad_search_range_s=float(self.settings.greedy_sentence_asr.vad_search_range_s),
            vad_valley_threshold=float(self.settings.greedy_sentence_asr.vad_valley_threshold),
            sentence_endings=str(self.settings.greedy_sentence_asr.sentence_endings),
            clause_endings=str(self.settings.greedy_sentence_asr.clause_endings),
        )

        # Create workdir for audio segments / merged chunks (cleaned up after stage)
        run_id = str(context.get("project_id") or context.get("job_id") or "unknown")
        base_dir = Path(self.settings.data_dir) / "workdir" / run_id
        greedy_dir = base_dir / "asr_greedy_windows"
        segments_dir = base_dir / "asr_segments"
        merged_dir = base_dir / "asr_merged_chunks"

        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            greedy_dir.mkdir(parents=True, exist_ok=True)
            logger.info("asr start (regions=%d)", len(vad_regions))
            started_at = time.monotonic()

            sentence_segments: list[SentenceSegment] = []
            sentence_vad_segments: list[VADSegment] = []
            window_index = count(1)
            greedy_ffmpeg_semaphore = asyncio.Semaphore(
                max(1, int(self.settings.asr.ffmpeg_concurrency))
            )

            async def _transcribe_window(start: float, end: float) -> str:
                window_id = next(window_index)
                tmp_path = greedy_dir / f"window_{window_id:06d}_{start:.2f}_{end:.2f}.wav"
                async with greedy_ffmpeg_semaphore:
                    await cut_audio_segment(
                        input_path=vocals_path,
                        output_path=str(tmp_path),
                        start=float(start),
                        end=float(end),
                        ffmpeg_bin=self.settings.audio.ffmpeg_bin,
                    )
                try:
                    async with tracker.acquire("asr"):
                        return str(
                            await self.provider.transcribe_segment(
                                str(tmp_path), float(start), float(end)
                            )
                            or ""
                        ).strip()
                finally:
                    try:
                        tmp_path.unlink(missing_ok=True)  # py311+
                    except Exception:
                        pass

            partitions = partition_vad_regions_by_gap(
                vad_regions,
                min_gap_seconds=float(self.settings.greedy_sentence_asr.parallel_gap_s),
            )
            logger.info(
                "asr greedy align (regions=%d, partitions=%d, partition_gap_s=%.2f)",
                len(vad_regions),
                len(partitions),
                float(self.settings.greedy_sentence_asr.parallel_gap_s),
            )

            async def _process_partition(
                region_ids: list[int],
            ) -> list[tuple[int, float, float]]:
                out: list[tuple[int, float, float]] = []
                for region_id in region_ids:
                    region = vad_regions[region_id]
                    segs = await greedy_sentence_align_region(
                        _transcribe_window,
                        frame_probs=vad_frame_probs,
                        frame_hop_s=float(frame_hop_s),
                        region_start=float(region.start),
                        region_end=float(region.end),
                        config=greedy_cfg,
                    )
                    out.extend([(int(region_id), float(s.start), float(s.end)) for s in segs])
                return out

            tasks = [_process_partition(p.region_ids()) for p in partitions]
            grouped = await asyncio.gather(*tasks)
            flat = [x for group in grouped for x in group]
            flat.sort(key=lambda t: (t[1], t[2]))

            for seg_id, (region_id, start, end_) in enumerate(flat):
                sentence_segments.append(
                    SentenceSegment(
                        id=int(seg_id),
                        start=float(start),
                        end=float(end_),
                        region_id=int(region_id),
                    )
                )
                sentence_vad_segments.append(VADSegment(start=float(start), end=float(end_)))

            # 1) Cut sentence segments audio (concurrent ffmpeg)
            time_ranges = [(float(seg.start), float(seg.end)) for seg in sentence_segments]
            segment_paths = await cut_audio_segments_batch(
                input_path=vocals_path,
                segments=time_ranges,
                output_dir=str(segments_dir),
                max_concurrent=int(self.settings.asr.ffmpeg_concurrency),
                ffmpeg_bin=self.settings.audio.ffmpeg_bin,
            )

            merged_specs = build_merged_chunk_specs(
                sentence_vad_segments,
                max_segments=int(self.settings.merged_chunk.max_segments),
                max_duration_s=float(self.settings.merged_chunk.max_duration_s),
            )

            total_tasks = len(segment_paths) + len(merged_specs)
            progress_done = 0
            progress_lock = asyncio.Lock()

            async def _report_progress(*, done: int, total: int, message: str) -> None:
                if not progress_reporter or total <= 0:
                    return
                pct = int(done / total * 100)
                if isinstance(progress_reporter, MetricsProgressReporter):
                    elapsed = max(0.001, time.monotonic() - started_at)
                    state = await tracker.snapshot("asr")
                    await progress_reporter.report_metrics(
                        {
                            "progress": pct,
                            "progress_message": message,
                            "items_processed": int(done),
                            "items_total": int(total),
                            "items_per_second": float(done) / elapsed,
                            "active_tasks": int(state.active),
                            "max_concurrent": int(state.max),
                        }
                    )
                else:
                    await progress_reporter.report(pct, message)

            await _report_progress(
                done=0,
                total=total_tasks,
                message=f"ASR 识别中 0/{max(1, total_tasks)}",
            )

            # 2. Transcribe all segments concurrently
            async def _transcribe_one(path: str) -> str:
                async with tracker.acquire("asr"):
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
            for i, (sent_seg, text) in enumerate(zip(sentence_segments, texts)):
                asr_segments.append(
                    ASRSegment(
                        id=i,
                        start=float(sent_seg.start),
                        end=float(sent_seg.end),
                        text=text.strip(),
                        language=source_language,
                    )
                )

            # 4. Build full transcript
            full_transcript = " ".join(seg.text for seg in asr_segments if seg.text)

            context["asr_segments"] = asr_segments
            context["full_transcript"] = full_transcript
            context["source_language"] = source_language
            context["sentence_segments"] = sentence_segments

            # 5. Merged-chunk ASR (global chunking; can cross VAD region boundaries)
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
                "asr done (sentence_segments=%d, asr_segments=%d, merged_chunks=%d)",
                len(sentence_segments),
                len(asr_segments),
                len(merged_chunks),
            )

        finally:
            # Cleanup temporary audio files
            if greedy_dir.exists():
                cleanup_segment_files([str(p) for p in greedy_dir.glob("*.wav")])
                try:
                    greedy_dir.rmdir()
                except OSError as exc:
                    logger.debug("failed to remove temp dir %s: %s", greedy_dir, exc)
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
