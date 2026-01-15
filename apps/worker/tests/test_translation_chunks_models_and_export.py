from __future__ import annotations

from subflow.export.subtitle_exporter import SubtitleExporter
from subflow.models.segment import ASRSegment, SemanticChunk, TranslationChunk
from subflow.models.serializers import deserialize_semantic_chunks, serialize_semantic_chunks


def test_semantic_chunk_serialization_roundtrip_translation_chunks() -> None:
    chunks = [
        SemanticChunk(
            id=0,
            text="src",
            translation="dst",
            asr_segment_ids=[0, 1],
            translation_chunks=[
                TranslationChunk(text="A", segment_id=0),
                TranslationChunk(text="B", segment_id=1),
            ],
        )
    ]

    payload = serialize_semantic_chunks(chunks)
    restored = deserialize_semantic_chunks(payload)

    assert restored[0].translation_chunks[0].text == "A"
    assert restored[0].translation_chunks[0].segment_id == 0
    assert restored[0].translation_chunks[1].text == "B"
    assert restored[0].translation_chunks[1].segment_id == 1


def test_deserialize_semantic_chunks_backfills_missing_translation_chunks() -> None:
    restored = deserialize_semantic_chunks(
        [{"id": 0, "text": "src", "translation": "dst", "asr_segment_ids": [2, 3]}]
    )
    assert len(restored[0].translation_chunks) == 2
    assert [c.segment_id for c in restored[0].translation_chunks] == [2, 3]
    assert "".join(c.text for c in restored[0].translation_chunks) == "dst"


def test_subtitle_exporter_per_chunk_leaves_uncovered_primary_empty() -> None:
    exporter = SubtitleExporter()
    asr_segments = [
        ASRSegment(id=0, start=0.0, end=1.0, text="s0"),
        ASRSegment(id=1, start=1.0, end=2.0, text="s1"),
    ]
    chunks = [
        SemanticChunk(
            id=0,
            text="src",
            translation="FULL",
            asr_segment_ids=[0, 1],
            translation_chunks=[TranslationChunk(text="only0", segment_id=0)],
        )
    ]

    entries = exporter.build_entries(
        chunks=chunks,
        asr_segments=asr_segments,
        asr_corrected_segments=None,
    )

    assert entries[0].primary_text == "only0"
    assert entries[1].primary_text == "FULL"
