"""Distribute a full translation into per-segment TranslationChunks."""

from __future__ import annotations

import math
import re
from typing import Sequence

from subflow.models.segment import ASRSegment, TranslationChunk

_PUNCTUATION_RE = re.compile(r"[。，！？；：,.!?;:]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _joiner_for_text(text: str) -> str:
    if any(ch.isspace() for ch in text):
        return " "
    if _contains_cjk(text):
        return ""
    return " "


def _split_on_punctuation(text: str) -> list[str]:
    pieces = re.split(_PUNCTUATION_RE, text)
    return [p.strip() for p in pieces if str(p).strip()]


def _split_units_no_punctuation(text: str) -> tuple[list[str], str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return [], ""
    if any(ch.isspace() for ch in cleaned):
        units = [u for u in cleaned.split() if u]
        return units, " "
    if _contains_cjk(cleaned):
        units = [ch for ch in cleaned if not ch.isspace()]
        return units, ""
    return list(cleaned), ""


def _split_piece_in_two(piece: str) -> tuple[str, str] | None:
    raw = str(piece or "").strip()
    if not raw:
        return None
    if any(ch.isspace() for ch in raw):
        words = [w for w in raw.split() if w]
        if len(words) < 2:
            return None
        mid = len(words) // 2
        left = " ".join(words[:mid]).strip()
        right = " ".join(words[mid:]).strip()
        if left and right:
            return left, right
        return None

    chars = [ch for ch in raw if not ch.isspace()]
    if len(chars) < 2:
        return None
    mid = len(chars) // 2
    left = "".join(chars[:mid]).strip()
    right = "".join(chars[mid:]).strip()
    if left and right:
        return left, right
    return None


def _subdivide_pieces(pieces: list[str], *, target_count: int) -> list[str]:
    out = [p for p in list(pieces or []) if str(p).strip()]
    if target_count <= 0:
        return []

    while len(out) < target_count:
        if not out:
            break
        longest_idx = max(range(len(out)), key=lambda i: len(out[i]))
        split = _split_piece_in_two(out[longest_idx])
        if split is None:
            break
        left, right = split
        out = out[:longest_idx] + [left, right] + out[longest_idx + 1 :]

    return out


def _allocate_counts_by_duration(total_pieces: int, segments: Sequence[ASRSegment]) -> list[int]:
    n = len(segments)
    if n <= 0:
        return []
    if total_pieces <= 0:
        return [0] * n
    if n == 1:
        return [total_pieces]

    if total_pieces < n:
        # Caller should avoid this by subdividing/duplicating, but keep it safe.
        return [1] * total_pieces + [0] * (n - total_pieces)

    counts = [1] * n
    remaining = total_pieces - n
    if remaining <= 0:
        return counts

    durations = [max(0.0, float(seg.end) - float(seg.start)) for seg in segments]
    total_duration = sum(durations)
    if total_duration <= 0:
        for i in range(remaining):
            counts[i % n] += 1
        return counts

    ideal_extras = [dur / total_duration * remaining for dur in durations]
    floor_extras = [int(math.floor(x)) for x in ideal_extras]
    for i, extra in enumerate(floor_extras):
        counts[i] += int(extra)
    remaining -= sum(floor_extras)

    if remaining <= 0:
        return counts

    order = sorted(
        range(n),
        key=lambda i: (ideal_extras[i] - floor_extras[i], durations[i]),
        reverse=True,
    )
    for i in range(remaining):
        counts[order[i % n]] += 1
    return counts


def distribute_translation(
    translation: str, segments: Sequence[ASRSegment]
) -> list[TranslationChunk]:
    """Split a full translation into per-segment TranslationChunks.

    Rules:
    - Prefer splitting on punctuation `。，！？；：,.!?;:` (punctuation removed).
    - If no punctuation, split evenly by characters (CJK: per char; others: words if spaced else chars).
    - Allocate punctuation pieces to segments by duration ratio.
    - No empty chunk is allowed unless translation itself is empty/whitespace.
    - If segments > pieces, the last piece is shared (duplicated) across remaining segments.
    """

    if not segments:
        return []

    text = str(translation or "").strip()
    if not text:
        return [TranslationChunk(text="", segment_id=int(seg.id)) for seg in segments]

    if len(segments) == 1:
        return [TranslationChunk(text=text, segment_id=int(segments[0].id))]

    if _PUNCTUATION_RE.search(text):
        pieces = _split_on_punctuation(text)
        if not pieces:
            pieces = [text]

        pieces = _subdivide_pieces(pieces, target_count=len(segments))
        if not pieces:
            pieces = [text]

        if len(pieces) < len(segments):
            pieces = pieces + [pieces[-1]] * (len(segments) - len(pieces))

        counts = _allocate_counts_by_duration(len(pieces), segments)
        joiner = _joiner_for_text(text)
        out: list[TranslationChunk] = []
        idx = 0
        for seg, cnt in zip(segments, counts, strict=False):
            take = max(1, int(cnt))
            assigned = pieces[idx : idx + take]
            idx += take
            if not assigned:
                assigned = [pieces[-1]]
            chunk_text = joiner.join(s.strip() for s in assigned if str(s).strip()).strip()
            if not chunk_text:
                chunk_text = pieces[-1].strip() or text
            out.append(TranslationChunk(text=chunk_text, segment_id=int(seg.id)))

        return out

    units, joiner = _split_units_no_punctuation(text)
    if not units:
        return [TranslationChunk(text=text, segment_id=int(seg.id)) for seg in segments]

    if len(units) < len(segments):
        units = units + [units[-1]] * (len(segments) - len(units))

    # Even split by unit count (not duration).
    base = len(units) // len(segments)
    extra = len(units) % len(segments)
    counts = [base + (1 if i < extra else 0) for i in range(len(segments))]

    out_units: list[TranslationChunk] = []
    idx = 0
    for seg, cnt in zip(segments, counts, strict=False):
        take = max(1, int(cnt))
        slice_units = units[idx : idx + take]
        idx += take
        if not slice_units:
            slice_units = [units[-1]]
        chunk_text = joiner.join(slice_units).strip()
        if not chunk_text:
            chunk_text = units[-1].strip() or text
        out_units.append(TranslationChunk(text=chunk_text, segment_id=int(seg.id)))
    return out_units
