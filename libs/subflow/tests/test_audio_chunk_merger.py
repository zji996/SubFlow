from __future__ import annotations

from subflow.models.segment import VADSegment
from subflow.utils.audio_chunk_merger import build_merged_chunk_specs


def test_build_merged_chunk_specs_splits_by_max_segments() -> None:
    segments = [VADSegment(start=float(i), end=float(i + 1)) for i in range(6)]
    chunks = build_merged_chunk_specs(segments, max_segments=3, max_duration_s=60.0)
    assert [(c.region_id, c.chunk_id, c.segment_ids) for c in chunks] == [
        (0, 0, [0, 1, 2]),
        (0, 1, [3, 4, 5]),
    ]
    assert (chunks[0].start, chunks[0].end) == (0.0, 3.0)
    assert (chunks[1].start, chunks[1].end) == (3.0, 6.0)


def test_build_merged_chunk_specs_splits_by_max_duration() -> None:
    segments = [
        VADSegment(start=0.0, end=10.0),
        VADSegment(start=10.0, end=20.0),
        VADSegment(start=20.0, end=30.0),
    ]
    chunks = build_merged_chunk_specs(segments, max_segments=99, max_duration_s=15.0)
    assert [c.segment_ids for c in chunks] == [[0], [1], [2]]
    assert [c.duration_s for c in chunks] == [10.0, 10.0, 10.0]


def test_build_merged_chunk_specs_allows_single_long_segment() -> None:
    segments = [VADSegment(start=0.0, end=100.0)]
    chunks = build_merged_chunk_specs(segments, max_segments=20, max_duration_s=60.0)
    assert len(chunks) == 1
    assert chunks[0].segment_ids == [0]
    assert chunks[0].duration_s == 100.0


def test_build_merged_chunk_specs_counts_gaps_in_duration_window() -> None:
    segments = [VADSegment(start=0.0, end=5.0), VADSegment(start=100.0, end=105.0)]
    chunks = build_merged_chunk_specs(segments, max_segments=20, max_duration_s=200.0)
    assert len(chunks) == 1
    assert chunks[0].segment_ids == [0, 1]
    assert chunks[0].duration_s == 105.0
