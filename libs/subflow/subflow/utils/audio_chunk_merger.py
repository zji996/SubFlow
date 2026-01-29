"""Build merged ASR audio chunks based on sentence segments.

This module is used by Stage 3 to build longer merged-audio windows for a second
ASR pass (merged ASR). Those windows are later consumed by Stage 4 for LLM-based
correction.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from subflow.models.segment import VADSegment
from subflow.utils.audio import cut_audio_segment


@dataclass(frozen=True)
class MergedChunkSpec:
    region_id: int
    chunk_id: int
    start: float
    end: float
    segment_ids: list[int]
    duration_s: float


def build_merged_chunk_specs(
    segments: list[VADSegment] | None,
    *,
    max_segments: int = 20,
    max_duration_s: float = 60.0,
) -> list[MergedChunkSpec]:
    """Group all segments into merged chunks (can cross VAD region boundaries).

    Chunk splitting rules:
    - Split when adding a segment would exceed `max_segments`.
    - Split when adding a segment would exceed `max_duration_s` (window length).

    Note: chunk duration is computed as the continuous window length (end - start),
    because merged chunks are cut from the original audio by [start, end] and thus
    include any silence gaps between segments.
    """
    segments = list(segments or [])
    if not segments:
        return []

    out: list[MergedChunkSpec] = []
    max_segments = max(1, int(max_segments))
    max_duration_s = float(max_duration_s)
    if max_duration_s <= 0:
        raise ValueError("max_duration_s must be > 0")

    # Sort by time but keep original ids stable.
    ordered = sorted(
        [(i, s) for i, s in enumerate(segments)],
        key=lambda x: (float(x[1].start), float(x[1].end), int(x[0])),
    )

    chunk_id = 0
    cur_ids: list[int] = []
    cur_start: float | None = None
    cur_end: float | None = None

    def _emit_current() -> None:
        nonlocal chunk_id, cur_ids, cur_start, cur_end
        if not cur_ids or cur_start is None or cur_end is None:
            return
        duration_s = max(0.0, float(cur_end) - float(cur_start))
        out.append(
            MergedChunkSpec(
                region_id=0,
                chunk_id=int(chunk_id),
                start=float(cur_start),
                end=float(cur_end),
                segment_ids=[int(x) for x in cur_ids],
                duration_s=float(duration_s),
            )
        )
        chunk_id += 1
        cur_ids = []
        cur_start = None
        cur_end = None

    for seg_id, seg in ordered:
        seg_start = float(seg.start)
        seg_end = float(seg.end)
        if not cur_ids or cur_start is None or cur_end is None:
            cur_ids = [int(seg_id)]
            cur_start = seg_start
            cur_end = seg_end
            continue

        next_end = max(float(cur_end), float(seg_end))
        next_duration = max(0.0, float(next_end) - float(cur_start))
        next_count = len(cur_ids) + 1

        should_split = (next_count > max_segments) or (next_duration > max_duration_s)
        if should_split:
            _emit_current()
            cur_ids = [int(seg_id)]
            cur_start = seg_start
            cur_end = seg_end
            continue

        cur_ids.append(int(seg_id))
        cur_end = next_end

    _emit_current()

    return out


async def cut_merged_chunk_audio(
    input_path: str,
    chunks: list[MergedChunkSpec],
    *,
    output_dir: str,
    ffmpeg_bin: str = "ffmpeg",
    max_concurrent: int = 4,
) -> list[str]:
    """Cut merged chunk audio files and return their paths in `chunks` order."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max(1, int(max_concurrent)))

    async def _one(spec: MergedChunkSpec) -> str:
        async with semaphore:
            out_path = out_dir / f"region_{spec.region_id:03d}_chunk_{spec.chunk_id:03d}.wav"
            await cut_audio_segment(
                input_path=input_path,
                output_path=str(out_path),
                start=float(spec.start),
                end=float(spec.end),
                ffmpeg_bin=ffmpeg_bin,
            )
            return str(out_path)

    tasks = [_one(spec) for spec in chunks]
    return list(await asyncio.gather(*tasks))
