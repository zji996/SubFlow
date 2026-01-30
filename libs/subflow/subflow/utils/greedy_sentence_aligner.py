"""Greedy sentence-aligned ASR utilities.

This module implements a lightweight PoC algorithm:
- For each coarse VAD region, slide a fixed-size window (e.g. 10s).
- Run ASR on the window, take the first sentence (by punctuation).
- Estimate sentence end time by character ratio, then refine the cut by searching
  a low-probability "valley" in frame-level VAD probabilities.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SentenceAlignedSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class GreedySentenceAlignerConfig:
    max_chunk_s: float = 10.0
    fallback_chunk_s: float = 15.0
    max_segment_s: float = 8.0  # Hard upper bound for segments without clear punctuation
    max_segment_chars: int = 50  # Prefer clause split only when text is long enough
    sentence_endings: str = "。？！；?!;."
    clause_endings: str = "，,、：:—–"
    vad_search_range_s: float = 1.0
    vad_valley_threshold: float = 0.3
    min_segment_s: float = 0.5
    min_boundary_search_s: float = 0.3
    max_loops_per_region: int = 10_000


TranscribeWindowFn = Callable[[float, float], Awaitable[str]]


_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


def _is_cjk_char(ch: str) -> bool:
    if not ch:
        return False
    code = ord(ch)
    # CJK Unified Ideographs + Ext A + Compatibility Ideographs
    return (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF) or (0xF900 <= code <= 0xFAFF)


def estimate_text_units(text: str) -> int:
    """Estimate subtitle length units.

    - Chinese (CJK) characters count as 1 unit each.
    - Latin "words" (A-Za-z0-9 tokens) count as 1 unit each.
    """
    raw = (text or "").strip()
    if not raw:
        return 0
    cjk = sum(1 for ch in raw if _is_cjk_char(ch))
    latin_words = len(_LATIN_WORD_RE.findall(raw))
    return int(cjk + latin_words)


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


def split_clause_by_max_units(
    text: str,
    *,
    clause_endings: str,
    max_units: int,
    max_ratio: float | None = None,
) -> tuple[str, str]:
    """Split at a clause boundary, preferring the longest prefix within `max_units`.

    When multiple clause-ending punctuation marks exist, this chooses the *last* boundary
    whose prefix length is <= `max_units` (so segments don't become too short).

    If `max_ratio` is provided, it is applied as an additional constraint on the selected
    prefix length (based on raw character ratio), used as a rough time-proxy.
    """
    raw = (text or "").strip()
    if not raw:
        return ("", "")

    endings = set(clause_endings)
    trailing = set("\"'”’)]}〉》」』")

    candidates: list[tuple[int, int, int]] = []
    # (units, end_idx, boundary_idx)
    for i, ch in enumerate(raw):
        if ch not in endings:
            continue
        end = i + 1
        while end < len(raw) and raw[end] in trailing:
            end += 1
        prefix = raw[:end].strip()
        units = estimate_text_units(prefix)
        if units <= 0:
            continue
        if max_ratio is not None and len(prefix) > int(round(len(raw) * float(max_ratio))):
            continue
        candidates.append((int(units), int(end), int(i)))

    if not candidates:
        return ("", raw)

    max_units = int(max(1, max_units))
    within = [c for c in candidates if int(c[0]) <= max_units]
    chosen = max(within, key=lambda t: (t[0], t[1])) if within else candidates[0]
    end = int(chosen[1])
    clause = raw[:end].strip()
    remaining = raw[end:].lstrip()
    return (clause, remaining)


def _probs_to_list(frame_probs: Sequence[float] | object) -> list[float]:
    tolist = getattr(frame_probs, "tolist", None)
    if callable(tolist):
        values = tolist()
        if isinstance(values, list):
            return [float(v) for v in values]
    if isinstance(frame_probs, Iterable):
        return [float(v) for v in frame_probs]
    return []


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
    """Greedy sentence-aligned ASR for a single VAD region.

    Key logic:
    - Try to find sentence-ending punctuation (。？！；?!;.) in max_chunk_s window
    - If not found but clause-ending punctuation (，,、：:—–) exists AND
      estimated text length exceeds max_segment_chars, split at clause
    - Otherwise extend to fallback_chunk_s and retry
    - This prevents super-long segments when speakers talk continuously
    """
    cfg = config or GreedySentenceAlignerConfig()
    start = float(region_start)
    end = float(region_end)
    if end <= start:
        return []

    max_seg_s = float(cfg.max_segment_s)
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

        # Step 1: Try to find sentence-ending punctuation
        sentence, _remaining = split_first_sentence(
            text, sentence_endings=str(cfg.sentence_endings)
        )

        # Step 2: If no sentence ending found, try clause ending (comma etc)
        if not sentence:
            max_units = int(cfg.max_segment_chars)
            units = estimate_text_units(text)
            max_ratio = None
            if chunk_end > cursor and max_seg_s > 0:
                max_ratio = min(1.0, float(max_seg_s) / float(chunk_end - cursor))
            if max_units > 0 and units >= max_units:
                clause, _remaining = split_clause_by_max_units(
                    text,
                    clause_endings=str(cfg.clause_endings),
                    max_units=max_units,
                    max_ratio=max_ratio,
                )
                if clause:
                    sentence = clause

        # Step 3: If still no sentence, extend window and retry
        if not sentence and chunk_end < end:
            extended_end = min(cursor + float(cfg.fallback_chunk_s), end)
            if extended_end > chunk_end:
                chunk_end = extended_end
                text = (await transcribe_window(cursor, chunk_end)).strip()
                sentence, _remaining = split_first_sentence(
                    text, sentence_endings=str(cfg.sentence_endings)
                )
                if not sentence:
                    max_units = int(cfg.max_segment_chars)
                    units = estimate_text_units(text)
                    max_ratio = None
                    if chunk_end > cursor and max_seg_s > 0:
                        max_ratio = min(1.0, float(max_seg_s) / float(chunk_end - cursor))
                    if max_units > 0 and units >= max_units:
                        clause, _remaining = split_clause_by_max_units(
                            text,
                            clause_endings=str(cfg.clause_endings),
                            max_units=max_units,
                            max_ratio=max_ratio,
                        )
                        if clause:
                            sentence = clause

        if not sentence:
            # No punctuation found at all; enforce max_segment_s as a hard upper bound.
            hard_end = min(end, cursor + float(max_seg_s)) if max_seg_s > 0 else float(chunk_end)
            if hard_end > cursor and hard_end < float(chunk_end) - 1e-6:
                hard_text = (await transcribe_window(cursor, hard_end)).strip()
                segments.append(
                    SentenceAlignedSegment(start=cursor, end=float(hard_end), text=hard_text)
                )
                cursor = float(hard_end)
            else:
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
