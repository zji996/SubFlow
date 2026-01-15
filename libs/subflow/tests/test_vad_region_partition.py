from __future__ import annotations

from subflow.models.segment import VADSegment
from subflow.utils.vad_region_partition import partition_vad_regions_by_gap


def test_partition_vad_regions_by_gap_empty_regions_returns_single_partition() -> None:
    parts = partition_vad_regions_by_gap([], min_gap_seconds=1.0)
    assert [(p.start_region_id, p.end_region_id) for p in parts] == [(0, 0)]


def test_partition_vad_regions_by_gap_single_region_returns_single_partition() -> None:
    parts = partition_vad_regions_by_gap([VADSegment(start=0.0, end=1.0)], min_gap_seconds=1.0)
    assert [(p.start_region_id, p.end_region_id) for p in parts] == [(0, 0)]


def test_partition_vad_regions_by_gap_merges_when_gap_smaller_than_threshold() -> None:
    regions = [
        VADSegment(start=0.9, end=75.02),
        VADSegment(start=75.44, end=82.9),  # gap = 0.42
    ]
    parts = partition_vad_regions_by_gap(regions, min_gap_seconds=1.0)
    assert [(p.start_region_id, p.end_region_id) for p in parts] == [(0, 1)]


def test_partition_vad_regions_by_gap_splits_when_gap_reaches_threshold() -> None:
    regions = [
        VADSegment(start=0.9, end=75.02),
        VADSegment(start=75.44, end=82.9),  # gap = 0.42
    ]
    parts = partition_vad_regions_by_gap(regions, min_gap_seconds=0.3)
    assert [(p.start_region_id, p.end_region_id) for p in parts] == [(0, 0), (1, 1)]
