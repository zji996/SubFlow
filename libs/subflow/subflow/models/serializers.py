"""Serialization helpers for artifacts stored in JSON."""

from __future__ import annotations

from typing import Any

from subflow.models.segment import (
    ASRCorrectedSegment,
    ASRMergedChunk,
    ASRSegment,
    SemanticChunk,
    TranslationChunk,
    VADSegment,
)


def _split_text_evenly(text: str, parts: int) -> list[str]:
    cleaned = str(text or "")
    if parts <= 0:
        return []
    if parts == 1:
        return [cleaned]
    n = len(cleaned)
    out: list[str] = []
    for i in range(parts):
        start = round(i * n / parts)
        end = round((i + 1) * n / parts)
        out.append(cleaned[start:end])
    return out


def serialize_vad_segments(segs: list[VADSegment]) -> list[dict[str, float]]:
    return [{"start": float(s.start), "end": float(s.end)} for s in segs]


def deserialize_vad_segments(items: list[dict[str, Any]]) -> list[VADSegment]:
    out: list[VADSegment] = []
    for item in items:
        out.append(VADSegment(start=float(item["start"]), end=float(item["end"])))
    return out


def serialize_asr_segments(segs: list[ASRSegment]) -> list[dict[str, Any]]:
    return [
        {
            "id": int(s.id),
            "start": float(s.start),
            "end": float(s.end),
            "text": str(s.text),
            "language": s.language,
        }
        for s in segs
    ]


def deserialize_asr_segments(items: list[dict[str, Any]]) -> list[ASRSegment]:
    out: list[ASRSegment] = []
    for item in items:
        out.append(
            ASRSegment(
                id=int(item["id"]),
                start=float(item["start"]),
                end=float(item["end"]),
                text=str(item["text"]),
                language=item.get("language"),
            )
        )
    return out


def serialize_asr_corrected_segments(
    items: dict[int, ASRCorrectedSegment],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for k in sorted(items.keys()):
        seg = items[k]
        out.append(
            {
                "id": int(seg.id),
                "asr_segment_id": int(seg.asr_segment_id),
                "text": seg.text,
            }
        )
    return out


def deserialize_asr_corrected_segments(
    items: list[dict[str, Any]],
) -> dict[int, ASRCorrectedSegment]:
    out: dict[int, ASRCorrectedSegment] = {}
    for item in items:
        seg_id = int(item["id"])
        out[seg_id] = ASRCorrectedSegment(
            id=seg_id,
            asr_segment_id=int(item.get("asr_segment_id", seg_id)),
            text=str(item.get("text", "")),
        )
    return out


def serialize_asr_merged_chunks(items: list[ASRMergedChunk]) -> list[dict[str, Any]]:
    return [
        {
            "region_id": int(c.region_id),
            "chunk_id": int(c.chunk_id),
            "start": float(c.start),
            "end": float(c.end),
            "segment_ids": [int(x) for x in list(c.segment_ids or [])],
            "text": str(c.text or ""),
        }
        for c in items
    ]


def deserialize_asr_merged_chunks(items: list[dict[str, Any]]) -> list[ASRMergedChunk]:
    out: list[ASRMergedChunk] = []
    for item in items:
        out.append(
            ASRMergedChunk(
                region_id=int(item.get("region_id") or 0),
                chunk_id=int(item.get("chunk_id") or 0),
                start=float(item.get("start") or 0.0),
                end=float(item.get("end") or 0.0),
                segment_ids=[int(x) for x in list(item.get("segment_ids") or [])],
                text=str(item.get("text") or ""),
            )
        )
    return out


def serialize_semantic_chunks(items: list[SemanticChunk]) -> list[dict[str, Any]]:
    return [
        {
            "id": int(c.id),
            "text": c.text,
            "translation": c.translation,
            "asr_segment_ids": [int(x) for x in list(c.asr_segment_ids or [])],
            "translation_chunks": [
                {
                    "text": str(ch.text or ""),
                    "segment_id": int(ch.segment_id),
                }
                for ch in list(c.translation_chunks or [])
            ],
        }
        for c in items
    ]


def deserialize_semantic_chunks(items: list[dict[str, Any]]) -> list[SemanticChunk]:
    out: list[SemanticChunk] = []
    for item in items:
        asr_segment_ids = [int(x) for x in list(item.get("asr_segment_ids") or [])]

        translation_chunks: list[TranslationChunk] = []
        raw_chunks = item.get("translation_chunks")
        if isinstance(raw_chunks, list):
            for ch in raw_chunks:
                if not isinstance(ch, dict):
                    continue
                text = str(ch.get("text") or "")
                raw_segment_id = ch.get("segment_id")
                if raw_segment_id is not None:
                    try:
                        translation_chunks.append(
                            TranslationChunk(text=text, segment_id=int(raw_segment_id))
                        )
                    except (TypeError, ValueError):
                        continue
                    continue

                raw_ids = ch.get("segment_ids")
                if not isinstance(raw_ids, list):
                    raw_ids = []
                for seg_id in [int(x) for x in list(raw_ids or [])]:
                    translation_chunks.append(TranslationChunk(text=text, segment_id=int(seg_id)))

        # Backward compatibility: legacy artifacts may contain per-segment translations.
        if not translation_chunks:
            raw_segment_translations = item.get("segment_translations")
            if isinstance(raw_segment_translations, list):
                for st in raw_segment_translations:
                    if not isinstance(st, dict):
                        continue
                    seg_id = st.get("asr_segment_id", st.get("segment_id", st.get("id")))
                    if seg_id is None:
                        continue
                    translation_chunks.append(
                        TranslationChunk(
                            text=str(st.get("text") or st.get("translation") or ""),
                            segment_id=int(seg_id),
                        )
                    )

        # Backward compatibility: if no chunks were stored, split full translation evenly per segment.
        if not translation_chunks and asr_segment_ids:
            pieces = _split_text_evenly(str(item.get("translation") or ""), len(asr_segment_ids))
            translation_chunks = [
                TranslationChunk(text=piece, segment_id=sid)
                for sid, piece in zip(asr_segment_ids, pieces, strict=False)
            ]

        if not asr_segment_ids and translation_chunks:
            covered: set[int] = set()
            for ch in translation_chunks:
                covered.add(int(ch.segment_id))
            asr_segment_ids = sorted(covered)

        out.append(
            SemanticChunk(
                id=int(item["id"]),
                text=str(item.get("text", "")),
                translation=str(item.get("translation", "")),
                asr_segment_ids=asr_segment_ids,
                translation_chunks=translation_chunks,
            )
        )
    return out
