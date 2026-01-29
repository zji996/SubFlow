import pytest

from subflow.utils.greedy_sentence_aligner import (
    GreedySentenceAlignerConfig,
    greedy_sentence_align_region,
)


@pytest.mark.asyncio
async def test_greedy_sentence_align_region_prefers_clause_punctuation_in_primary_window() -> None:
    """When segment duration exceeds max_segment_s and no sentence-ending punctuation,
    prefer splitting at clause-ending punctuation (comma) rather than extending window."""
    calls: list[tuple[float, float]] = []

    async def _transcribe_window(start: float, end: float) -> str:
        calls.append((float(start), float(end)))
        return "Hello, world"

    # Set max_segment_s=4.0 so that estimated clause end (~5s) exceeds it,
    # triggering forced split at comma without extending to fallback window.
    cfg = GreedySentenceAlignerConfig(
        max_chunk_s=10.0, fallback_chunk_s=15.0, max_segment_s=4.0, max_loops_per_region=1
    )
    segs = await greedy_sentence_align_region(
        _transcribe_window,
        frame_probs=[1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        frame_hop_s=1.0,
        region_start=0.0,
        region_end=15.0,
        config=cfg,
    )

    assert calls == [(0.0, 10.0)]
    assert len(segs) == 1
    assert segs[0].text == "Hello,"
    assert segs[0].end == 5.0


@pytest.mark.asyncio
async def test_greedy_sentence_skips_clause_when_segment_shorter_than_max() -> None:
    """When segment duration is below max_segment_s, skip clause punctuation and
    extend window to search for sentence-ending punctuation."""
    calls: list[tuple[float, float]] = []

    async def _transcribe_window(start: float, end: float) -> str:
        calls.append((float(start), float(end)))
        if end <= 10.0:
            return "Hello, world"
        # Extended window has sentence-ending punctuation
        return "Hello, world. And more text continues here"

    # With max_segment_s=10.0 (default), "Hello," at ~5s is below threshold,
    # so it will extend to fallback window and find the sentence-ending period.
    cfg = GreedySentenceAlignerConfig(
        max_chunk_s=10.0, fallback_chunk_s=15.0, max_segment_s=10.0, max_loops_per_region=1
    )
    segs = await greedy_sentence_align_region(
        _transcribe_window,
        frame_probs=[1.0] * 16,  # All high prob (no valley)
        frame_hop_s=1.0,
        region_start=0.0,
        region_end=15.0,
        config=cfg,
    )

    # Should extend to fallback window to find the period
    assert calls == [(0.0, 10.0), (0.0, 15.0)]
    assert len(segs) == 1
    assert segs[0].text == "Hello, world."


@pytest.mark.asyncio
async def test_greedy_sentence_align_region_falls_back_to_clause_punctuation_in_extended_window() -> (
    None
):
    calls: list[tuple[float, float]] = []

    async def _transcribe_window(start: float, end: float) -> str:
        calls.append((float(start), float(end)))
        if end <= 10.0:
            return "Hello world"
        return "Hello, world"

    cfg = GreedySentenceAlignerConfig(
        max_chunk_s=10.0, fallback_chunk_s=15.0, max_loops_per_region=1
    )
    segs = await greedy_sentence_align_region(
        _transcribe_window,
        frame_probs=[
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            0.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
        ],
        frame_hop_s=1.0,
        region_start=0.0,
        region_end=15.0,
        config=cfg,
    )

    assert calls == [(0.0, 10.0), (0.0, 15.0)]
    assert len(segs) == 1
    assert segs[0].text == "Hello,"
    assert segs[0].end == 7.0


@pytest.mark.asyncio
async def test_greedy_sentence_align_region_retries_with_fallback_window() -> None:
    calls: list[tuple[float, float]] = []

    async def _transcribe_window(start: float, end: float) -> str:
        calls.append((float(start), float(end)))
        if end <= 10.0:
            return "no punctuation here and keeps going"
        return "First sentence. Second sentence continues"

    cfg = GreedySentenceAlignerConfig(max_chunk_s=10.0, fallback_chunk_s=15.0)
    segs = await greedy_sentence_align_region(
        _transcribe_window,
        frame_probs=[],
        frame_hop_s=0.02,
        region_start=0.0,
        region_end=15.0,
        config=cfg,
    )

    assert calls == [(0.0, 10.0), (0.0, 15.0)]
    assert len(segs) == 1
    assert segs[0].start == 0.0
    assert segs[0].end == 15.0
    assert segs[0].text == "First sentence."


@pytest.mark.asyncio
async def test_greedy_sentence_align_region_forces_split_at_fallback_end() -> None:
    calls: list[tuple[float, float]] = []

    async def _transcribe_window(start: float, end: float) -> str:
        calls.append((float(start), float(end)))
        return "still no punctuation even with a longer window"

    cfg = GreedySentenceAlignerConfig(max_chunk_s=10.0, fallback_chunk_s=15.0)
    segs = await greedy_sentence_align_region(
        _transcribe_window,
        frame_probs=[],
        frame_hop_s=0.02,
        region_start=0.0,
        region_end=15.0,
        config=cfg,
    )

    assert calls == [(0.0, 10.0), (0.0, 15.0)]
    assert len(segs) == 1
    assert segs[0].start == 0.0
    assert segs[0].end == 15.0
    assert segs[0].text == "still no punctuation even with a longer window"


@pytest.mark.asyncio
async def test_greedy_sentence_align_region_does_not_retry_when_at_region_end() -> None:
    calls: list[tuple[float, float]] = []

    async def _transcribe_window(start: float, end: float) -> str:
        calls.append((float(start), float(end)))
        return "no punctuation but region is shorter than max_chunk_s"

    cfg = GreedySentenceAlignerConfig(max_chunk_s=10.0, fallback_chunk_s=15.0)
    segs = await greedy_sentence_align_region(
        _transcribe_window,
        frame_probs=[],
        frame_hop_s=0.02,
        region_start=0.0,
        region_end=9.0,
        config=cfg,
    )

    assert calls == [(0.0, 9.0)]
    assert len(segs) == 1
    assert segs[0].start == 0.0
    assert segs[0].end == 9.0
