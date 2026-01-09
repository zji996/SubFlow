from __future__ import annotations

from subflow.models.segment import ASRCorrectedSegment, ASRMergedChunk, ASRSegment, SemanticChunk, TranslationChunk, VADSegment
from subflow.models.serializers import (
    deserialize_asr_corrected_segments,
    deserialize_asr_merged_chunks,
    deserialize_asr_segments,
    deserialize_semantic_chunks,
    deserialize_vad_segments,
    serialize_asr_corrected_segments,
    serialize_asr_merged_chunks,
    serialize_asr_segments,
    serialize_semantic_chunks,
    serialize_vad_segments,
)


def test_vad_roundtrip() -> None:
    items = [VADSegment(start=0.1, end=1.2), VADSegment(start=2.0, end=3.0)]
    raw = serialize_vad_segments(items)
    restored = deserialize_vad_segments(raw)
    assert restored == items


def test_asr_segments_roundtrip() -> None:
    items = [
        ASRSegment(id=0, start=0.0, end=1.0, text="hi", language="en"),
        ASRSegment(id=1, start=1.0, end=2.0, text="there", language=None),
    ]
    raw = serialize_asr_segments(items)
    restored = deserialize_asr_segments(raw)
    assert [s.id for s in restored] == [0, 1]
    assert restored[0].language == "en"


def test_asr_corrected_segments_roundtrip_sorted() -> None:
    corrected = {
        2: ASRCorrectedSegment(id=2, asr_segment_id=2, text="c"),
        1: ASRCorrectedSegment(id=1, asr_segment_id=1, text="b"),
    }
    raw = serialize_asr_corrected_segments(corrected)
    assert [x["id"] for x in raw] == [1, 2]
    restored = deserialize_asr_corrected_segments(raw)
    assert restored[1].text == "b"
    assert restored[2].text == "c"


def test_asr_merged_chunks_roundtrip() -> None:
    merged = [
        ASRMergedChunk(region_id=0, chunk_id=0, start=0.0, end=2.0, segment_ids=[0, 1], text="hello"),
    ]
    raw = serialize_asr_merged_chunks(merged)
    restored = deserialize_asr_merged_chunks(raw)
    assert restored[0].segment_ids == [0, 1]
    assert restored[0].text == "hello"


def test_semantic_chunks_roundtrip_with_translation_chunks() -> None:
    chunks = [
        SemanticChunk(
            id=0,
            text="a b",
            translation="甲乙",
            asr_segment_ids=[0, 1],
            translation_chunks=[
                TranslationChunk(text="甲", segment_ids=[0]),
                TranslationChunk(text="乙", segment_ids=[1]),
            ],
        )
    ]
    raw = serialize_semantic_chunks(chunks)
    restored = deserialize_semantic_chunks(raw)
    assert restored[0].asr_segment_ids == [0, 1]
    assert restored[0].translation_chunks and restored[0].translation_chunks[0].text == "甲"


def test_deserialize_semantic_chunks_legacy_segment_translations() -> None:
    raw = [
        {
            "id": 0,
            "text": "x y",
            "translation": "",
            "asr_segment_ids": [0, 1],
            "segment_translations": [
                {"asr_segment_id": 0, "text": "甲"},
                {"asr_segment_id": 1, "translation": "乙"},
            ],
        }
    ]
    restored = deserialize_semantic_chunks(raw)
    assert restored[0].translation_chunks and len(restored[0].translation_chunks) == 2
    assert restored[0].translation_chunks[0].segment_ids == [0]
    assert restored[0].translation_chunks[0].text == "甲"


def test_deserialize_semantic_chunks_fallback_full_translation() -> None:
    raw = [
        {"id": 0, "text": "x", "translation": "甲", "asr_segment_ids": [0], "translation_chunks": []},
    ]
    restored = deserialize_semantic_chunks(raw)
    assert restored[0].translation_chunks
    assert restored[0].translation_chunks[0].text == "甲"
    assert restored[0].translation_chunks[0].segment_ids == [0]

