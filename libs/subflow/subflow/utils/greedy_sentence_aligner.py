"""Greedy sentence-aligned ASR utilities.

This module implements a lightweight PoC algorithm:
- For each coarse VAD region, slide a fixed-size window (e.g. 10s).
- Run ASR on the window, take the first sentence (by punctuation).
- Estimate sentence end time by character ratio, then refine the cut by searching
  a low-probability "valley" in frame-level VAD probabilities.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SentenceAlignedSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class GreedySentenceAlignerConfig:
    max_chunk_s: float = 10.0
    fallback_chunk_s: float = 15.0
    sentence_endings: str = "。？！；?!;."
    clause_endings: str = "，,、：:—–"
    vad_search_range_s: float = 1.0
    vad_valley_threshold: float = 0.3
    min_segment_s: float = 0.5
    min_boundary_search_s: float = 0.3
    max_loops_per_region: int = 10_000


TranscribeWindowFn = Callable[[float, float], Awaitable[str]]


def split_first_sentence(text: str, *, sentence_endings: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return ("", "")

    endings = set(sentence_endings)
    trailing = set("\"'”’)]}〉》」』")

    boundary: int | None = None
    for i, ch in enumerate(raw):
        if ch not in endings:
            continue
        if ch == ".":
            nxt = raw[i + 1] if i + 1 < len(raw) else ""
            if nxt and (not nxt.isspace()) and (nxt not in trailing):
                continue
        boundary = i
        break

    if boundary is None:
        return ("", raw)

    end = boundary + 1
    while end < len(raw) and raw[end] in trailing:
        end += 1

    sentence = raw[:end].strip()
    remaining = raw[end:].lstrip()
    return (sentence, remaining)


def split_first_clause(text: str, *, clause_endings: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return ("", "")

    endings = set(clause_endings)
    trailing = set("\"'”’)]}〉》」』")

    boundary: int | None = None
    for i, ch in enumerate(raw):
        if ch in endings:
            boundary = i
            break

    if boundary is None:
        return ("", raw)

    end = boundary + 1
    while end < len(raw) and raw[end] in trailing:
        end += 1

    clause = raw[:end].strip()
    remaining = raw[end:].lstrip()
    return (clause, remaining)


def _probs_to_list(frame_probs: Sequence[float] | object) -> list[float]:
    tolist = getattr(frame_probs, "tolist", None)
    if callable(tolist):
        values = tolist()
        if isinstance(values, list):
            return [float(v) for v in values]
    return [float(v) for v in frame_probs]  # type: ignore[arg-type]


def find_vad_valley(
    frame_probs: Sequence[float] | object,
    *,
    target_time: float,
    search_range_s: float,
    min_time: float,
    max_time: float,
    frame_hop_s: float,
    valley_threshold: float,
    min_valley_s: float = 0.08,
) -> float:
    """Find a cut time near `target_time` by searching a low-probability VAD valley."""
    if max_time <= min_time:
        return float(max_time)

    probs = _probs_to_list(frame_probs)
    if not probs or frame_hop_s <= 0:
        return float(max_time)

    hop = float(frame_hop_s)
    n = len(probs)

    target_time = float(min(max(target_time, min_time), max_time))
    range_frames = max(1, int(round(float(search_range_s) / hop)))

    min_frame = max(0, int(min_time / hop))
    max_frame = min(n - 1, int(max_time / hop))
    if max_frame <= min_frame:
        return float(max_time)

    target_frame = int(target_time / hop)
    lo = max(min_frame, target_frame - range_frames)
    hi = min(max_frame, target_frame + range_frames)
    if hi <= lo:
        return target_time

    thr = float(valley_threshold)
    min_valley_frames = max(1, int(round(float(min_valley_s) / hop)))

    best: tuple[float, float, int] | None = None
    run_start: int | None = None

    def _consider_run(start: int, end: int) -> None:
        nonlocal best
        if end - start + 1 < min_valley_frames:
            return
        center = (start + end) // 2
        dist = abs(center - target_frame)
        mean_p = sum(probs[start : end + 1]) / float(end - start + 1)
        score = (float(dist), float(mean_p), int(center))
        if best is None or score < best:
            best = score

    for i in range(lo, hi + 1):
        is_below = float(probs[i]) < thr
        if is_below and run_start is None:
            run_start = i
        if (not is_below) and run_start is not None:
            _consider_run(run_start, i - 1)
            run_start = None
    if run_start is not None:
        _consider_run(run_start, hi)

    if best is not None:
        chosen_frame = best[2]
    else:
        window = probs[lo : hi + 1]
        local_min_i = min(range(len(window)), key=lambda j: float(window[j]))
        chosen_frame = lo + int(local_min_i)

    cut_time = float(chosen_frame) * hop
    if cut_time < min_time:
        cut_time = float(min_time)
    if cut_time > max_time:
        cut_time = float(max_time)
    return cut_time


async def greedy_sentence_align_region(
    transcribe_window: TranscribeWindowFn,
    *,
    frame_probs: Sequence[float] | object,
    frame_hop_s: float,
    region_start: float,
    region_end: float,
    config: GreedySentenceAlignerConfig | None = None,
) -> list[SentenceAlignedSegment]:
    cfg = config or GreedySentenceAlignerConfig()
    start = float(region_start)
    end = float(region_end)
    if end <= start:
        return []

    segments: list[SentenceAlignedSegment] = []
    cursor = start
    loops = 0

    while cursor < end:
        loops += 1
        if loops > int(cfg.max_loops_per_region):
            break

        chunk_end = min(cursor + float(cfg.max_chunk_s), end)
        if chunk_end - cursor < float(cfg.min_segment_s):
            break

        text = (await transcribe_window(cursor, chunk_end)).strip()
        if not text:
            cursor = chunk_end
            continue

        sentence, _remaining = split_first_sentence(
            text, sentence_endings=str(cfg.sentence_endings)
        )
        if not sentence:
            clause, _remaining = split_first_clause(text, clause_endings=str(cfg.clause_endings))
            if clause:
                sentence = clause

        if not sentence and chunk_end < end:
            extended_end = min(cursor + float(cfg.fallback_chunk_s), end)
            if extended_end > chunk_end:
                chunk_end = extended_end
                text = (await transcribe_window(cursor, chunk_end)).strip()
                sentence, _remaining = split_first_sentence(
                    text, sentence_endings=str(cfg.sentence_endings)
                )
                if not sentence:
                    clause, _remaining = split_first_clause(
                        text, clause_endings=str(cfg.clause_endings)
                    )
                    if clause:
                        sentence = clause

        if not sentence:
            segments.append(SentenceAlignedSegment(start=cursor, end=chunk_end, text=text))
            cursor = chunk_end
            continue

        ratio = float(len(sentence)) / float(max(1, len(text)))
        estimated_end = cursor + (chunk_end - cursor) * max(0.0, min(1.0, ratio))

        min_time = min(
            chunk_end, cursor + max(float(cfg.min_segment_s), float(cfg.min_boundary_search_s))
        )
        actual_end = find_vad_valley(
            frame_probs,
            target_time=estimated_end,
            search_range_s=float(cfg.vad_search_range_s),
            min_time=min_time,
            max_time=chunk_end,
            frame_hop_s=float(frame_hop_s),
            valley_threshold=float(cfg.vad_valley_threshold),
        )
        actual_end = float(min(max(actual_end, min_time), chunk_end))
        if actual_end <= cursor:
            actual_end = float(chunk_end)

        segments.append(SentenceAlignedSegment(start=cursor, end=actual_end, text=sentence.strip()))
        if chunk_end - actual_end < float(cfg.min_segment_s):
            cursor = chunk_end
        else:
            cursor = actual_end

    return segments


async def greedy_sentence_align(
    transcribe_window: TranscribeWindowFn,
    *,
    vad_regions: Sequence[tuple[float, float]],
    frame_probs: Sequence[float] | object,
    frame_hop_s: float,
    config: GreedySentenceAlignerConfig | None = None,
) -> list[SentenceAlignedSegment]:
    out: list[SentenceAlignedSegment] = []
    for region_start, region_end in vad_regions:
        out.extend(
            await greedy_sentence_align_region(
                transcribe_window,
                frame_probs=frame_probs,
                frame_hop_s=frame_hop_s,
                region_start=float(region_start),
                region_end=float(region_end),
                config=config,
            )
        )
    return out
