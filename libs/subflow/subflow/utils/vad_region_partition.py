"""VAD region-gap based partitioning utilities."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from subflow.models.segment import VADSegment


@dataclass(frozen=True)
class RegionPartition:
    """A contiguous region-id partition [start_region_id, end_region_id]."""

    start_region_id: int
    end_region_id: int

    def region_ids(self) -> list[int]:
        if self.end_region_id < self.start_region_id:
            return []
        return list(range(int(self.start_region_id), int(self.end_region_id) + 1))


def partition_vad_regions_by_gap(
    vad_regions: Sequence[VADSegment] | None,
    *,
    min_gap_seconds: float,
) -> list[RegionPartition]:
    """Partition VAD regions by inter-region silence gaps.

    A new partition starts when `next.start - prev.end >= min_gap_seconds`.

    Notes:
    - Regions are assumed to be in chronological order (as produced by VAD).
    - If `vad_regions` is empty, returns a single implicit partition (0..0) so
      downstream code can treat all data as one region group.
    """
    regions = list(vad_regions or [])
    if not regions:
        return [RegionPartition(start_region_id=0, end_region_id=0)]

    threshold = float(min_gap_seconds)
    start = 0
    out: list[RegionPartition] = []

    for i in range(1, len(regions)):
        prev = regions[i - 1]
        cur = regions[i]
        gap = float(cur.start) - float(prev.end)
        if gap >= threshold:
            out.append(RegionPartition(start_region_id=start, end_region_id=i - 1))
            start = i

    out.append(RegionPartition(start_region_id=start, end_region_id=len(regions) - 1))
    return out

