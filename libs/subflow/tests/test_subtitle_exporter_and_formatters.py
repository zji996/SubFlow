from __future__ import annotations

import json

import pytest

from subflow.export.subtitle_exporter import SubtitleExporter
from subflow.models.segment import (
    ASRCorrectedSegment,
    ASRSegment,
    SegmentTranslation,
    SemanticChunk,
    TranslationChunk,
)
from subflow.models.subtitle_types import (
    SubtitleContent,
    SubtitleEntry,
    SubtitleExportConfig,
    SubtitleFormat,
)


def _demo_entries() -> list[SubtitleEntry]:
    return [
        SubtitleEntry(index=1, start=0.0, end=1.0, primary_text="甲", secondary_text="a"),
        SubtitleEntry(index=2, start=1.0, end=2.0, primary_text="乙", secondary_text="b"),
    ]


def test_export_entries_validates_config() -> None:
    exporter = SubtitleExporter()
    config = SubtitleExportConfig(
        format=SubtitleFormat.SRT, content=SubtitleContent.BOTH, primary_position="middle"
    )
    with pytest.raises(ValueError, match="primary_position"):
        exporter.export_entries(_demo_entries(), config)


def test_srt_export_contains_timestamps_and_lines() -> None:
    exporter = SubtitleExporter()
    config = SubtitleExportConfig(
        format=SubtitleFormat.SRT, content=SubtitleContent.BOTH, primary_position="top"
    )
    out = exporter.export_entries(_demo_entries(), config)
    assert "1\n" in out
    assert "00:00:00,000 --> 00:00:01,000" in out
    assert "甲" in out and "a" in out


def test_vtt_export_has_header() -> None:
    exporter = SubtitleExporter()
    config = SubtitleExportConfig(
        format=SubtitleFormat.VTT, content=SubtitleContent.BOTH, primary_position="top"
    )
    out = exporter.export_entries(_demo_entries(), config)
    assert out.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.000" in out


def test_ass_export_contains_dialogue_lines() -> None:
    exporter = SubtitleExporter()
    config = SubtitleExportConfig(
        format=SubtitleFormat.ASS, content=SubtitleContent.BOTH, primary_position="top"
    )
    out = exporter.export_entries(_demo_entries(), config)
    assert "[V4+ Styles]" in out
    assert "Dialogue:" in out


def test_json_export_is_valid_json() -> None:
    exporter = SubtitleExporter()
    config = SubtitleExportConfig(
        format=SubtitleFormat.JSON, content=SubtitleContent.BOTH, primary_position="top"
    )
    out = exporter.export_entries(_demo_entries(), config)
    payload = json.loads(out)
    assert payload["version"] == "1.0"
    assert payload["entries"][0]["primary_text"] == "甲"


def test_build_entries_uses_segment_translations_when_provided() -> None:
    exporter = SubtitleExporter()
    chunks = [
        SemanticChunk(
            id=0,
            text="a b",
            translation="全翻译",
            asr_segment_ids=[0, 1],
            translation_chunks=[
                TranslationChunk(text="甲", segment_id=0),
                TranslationChunk(text="乙", segment_id=1),
            ],
        )
    ]
    asr_segments = [
        ASRSegment(id=0, start=0.0, end=1.0, text="a", language="en"),
        ASRSegment(id=1, start=1.0, end=2.0, text="b", language="en"),
    ]
    corrected = {0: ASRCorrectedSegment(id=0, asr_segment_id=0, text="A")}

    entries = exporter.build_entries(
        chunks,
        asr_segments,
        corrected,
        segment_translations=[
            SegmentTranslation(segment_id=0, source_text="A", translation="T0"),
            SegmentTranslation(segment_id=1, source_text="b", translation="T1"),
        ],
    )
    assert [e.primary_text for e in entries] == ["T0", "T1"]
    assert [e.secondary_text for e in entries] == ["A", "b"]


def test_build_entries_legacy_translation_chunks_override_chunk_translation() -> None:
    exporter = SubtitleExporter()
    chunks = [
        SemanticChunk(
            id=0,
            text="a b",
            translation="FULL",
            asr_segment_ids=[0, 1],
            translation_chunks=[TranslationChunk(text="only0", segment_id=0)],
        )
    ]
    asr_segments = [
        ASRSegment(id=0, start=0.0, end=1.0, text="a", language="en"),
        ASRSegment(id=1, start=1.0, end=2.0, text="b", language="en"),
    ]
    entries = exporter.build_entries(chunks, asr_segments, None)
    assert [e.primary_text for e in entries] == ["only0", "FULL"]
