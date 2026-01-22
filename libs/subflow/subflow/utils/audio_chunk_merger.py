"""Build merged ASR audio chunks based on VAD regions/segments."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from subflow.models.segment import VADSegment
from subflow.utils.audio import cut_audio_segment
from subflow.utils.vad_region_mapper import build_region_segment_ids


@dataclass(frozen=True)
class MergedChunkSpec:
    region_id: int
    chunk_id: int
    start: float
    end: float
    segment_ids: list[int]
    duration_s: float


def build_merged_chunk_specs(
    vad_regions: list[VADSegment] | None,
    segments: list[VADSegment] | None,
    *,
    max_chunk_s: float = 30.0,
) -> list[MergedChunkSpec]:
    """Group segments within each region into <= max_chunk_s chunks.

    Chunk duration is computed as the continuous window length (end - start),
    because merged chunks are cut from the original audio by [start, end].
    """
    regions = list(vad_regions or [])
    segments = list(segments or [])
    if not segments:
        return []

    region_segment_ids = build_region_segment_ids(regions, segments)
    if not region_segment_ids and segments:
        region_segment_ids = [list(range(len(segments)))]

    out: list[MergedChunkSpec] = []

    for region_id, seg_ids in enumerate(region_segment_ids):
        if not seg_ids:
            continue
        chunk_id = 0
        cur_ids: list[int] = []
        cur_start: float | None = None
        cur_end: float | None = None
        cur_window_dur: float = 0.0

        for seg_id in seg_ids:
            seg = segments[seg_id]
            seg_start = float(seg.start)
            seg_end = float(seg.end)
            if cur_start is None or cur_end is None or not cur_ids:
                cur_ids = [int(seg_id)]
                cur_start = seg_start
                cur_end = seg_end
                cur_window_dur = max(0.0, cur_end - cur_start)
                continue

            next_end = max(cur_end, seg_end)
            next_window_dur = max(0.0, next_end - cur_start)
            if next_window_dur <= max_chunk_s:
                cur_ids.append(int(seg_id))
                cur_end = next_end
                cur_window_dur = next_window_dur
                continue

            out.append(
                MergedChunkSpec(
                    region_id=region_id,
                    chunk_id=chunk_id,
                    start=cur_start,
                    end=cur_end,
                    segment_ids=cur_ids,
                    duration_s=float(cur_window_dur),
                )
            )
            chunk_id += 1
            cur_ids = [int(seg_id)]
            cur_start = seg_start
            cur_end = seg_end
            cur_window_dur = max(0.0, cur_end - cur_start)

        if cur_ids and cur_start is not None and cur_end is not None:
            out.append(
                MergedChunkSpec(
                    region_id=region_id,
                    chunk_id=chunk_id,
                    start=cur_start,
                    end=cur_end,
                    segment_ids=cur_ids,
                    duration_s=float(cur_window_dur),
                )
            )

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
