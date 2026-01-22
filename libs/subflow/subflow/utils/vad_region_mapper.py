"""Utilities to map VAD regions to child segments."""

from __future__ import annotations

from collections.abc import Sequence

from subflow.models.segment import VADSegment


def build_region_segment_ids(
    vad_regions: Sequence[VADSegment] | None,
    segments: Sequence[VADSegment] | None,
    *,
    eps: float = 1e-3,
) -> list[list[int]]:
    """Build region -> segment index mapping.

    A segment is assigned to a region if it overlaps that region. Inputs are
    expected to be in chronological order; if regions are empty, a single
    region covering all segments is returned.
    """
    regions = list(vad_regions or [])
    segments = list(segments or [])
    if not segments:
        return []
    if not regions:
        return [list(range(len(segments)))]

    regions_sorted = sorted(enumerate(regions), key=lambda x: (float(x[1].start), float(x[1].end)))
    seg_idx = 0
    out_by_region_id: dict[int, list[int]] = {i: [] for i in range(len(regions))}

    # Assume non-overlapping, non-decreasing regions; assign each segment to at most one region.
    for region_id, region in regions_sorted:
        r_start = float(region.start) - eps
        r_end = float(region.end) + eps

        while seg_idx < len(segments) and float(segments[seg_idx].end) < r_start:
            seg_idx += 1

        while seg_idx < len(segments) and float(segments[seg_idx].start) <= r_end:
            seg = segments[seg_idx]
            s_start = float(seg.start)
            s_end = float(seg.end)
            if s_end >= r_start and s_start <= r_end:
                out_by_region_id[region_id].append(seg_idx)
            seg_idx += 1

    # Preserve original region order.
    return [out_by_region_id[i] for i in range(len(regions))]
