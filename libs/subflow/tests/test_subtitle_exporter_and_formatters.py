from __future__ import annotations

import json

import pytest

from subflow.export.subtitle_exporter import SubtitleExporter
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk, TranslationChunk
from subflow.models.subtitle_types import (
    SubtitleContent,
    SubtitleEntry,
    SubtitleExportConfig,
    SubtitleFormat,
    TranslationStyle,
)


def _demo_entries() -> list[SubtitleEntry]:
    return [
        SubtitleEntry(index=1, start=0.0, end=1.0, primary_text="甲", secondary_text="a"),
        SubtitleEntry(index=2, start=1.0, end=2.0, primary_text="乙", secondary_text="b"),
    ]


def test_export_entries_validates_config() -> None:
    exporter = SubtitleExporter()
    config = SubtitleExportConfig(format=SubtitleFormat.SRT, content=SubtitleContent.BOTH, primary_position="middle")
    with pytest.raises(ValueError, match="primary_position"):
        exporter.export_entries(_demo_entries(), config)


def test_srt_export_contains_timestamps_and_lines() -> None:
    exporter = SubtitleExporter()
    config = SubtitleExportConfig(format=SubtitleFormat.SRT, content=SubtitleContent.BOTH, primary_position="top")
    out = exporter.export_entries(_demo_entries(), config)
    assert "1\n" in out
    assert "00:00:00,000 --> 00:00:01,000" in out
    assert "甲" in out and "a" in out


def test_vtt_export_has_header() -> None:
    exporter = SubtitleExporter()
    config = SubtitleExportConfig(format=SubtitleFormat.VTT, content=SubtitleContent.BOTH, primary_position="top")
    out = exporter.export_entries(_demo_entries(), config)
    assert out.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.000" in out


def test_ass_export_contains_dialogue_lines() -> None:
    exporter = SubtitleExporter()
    config = SubtitleExportConfig(format=SubtitleFormat.ASS, content=SubtitleContent.BOTH, primary_position="top")
    out = exporter.export_entries(_demo_entries(), config)
    assert "[V4+ Styles]" in out
    assert "Dialogue:" in out


def test_json_export_is_valid_json() -> None:
    exporter = SubtitleExporter()
    config = SubtitleExportConfig(format=SubtitleFormat.JSON, content=SubtitleContent.BOTH, primary_position="top")
    out = exporter.export_entries(_demo_entries(), config)
    payload = json.loads(out)
    assert payload["version"] == "1.0"
    assert payload["entries"][0]["primary_text"] == "甲"


def test_build_entries_translation_style_per_chunk_and_full() -> None:
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

    per_chunk = exporter.build_entries(chunks, asr_segments, corrected, translation_style=TranslationStyle.PER_CHUNK)
    assert [e.primary_text for e in per_chunk] == ["甲", "乙"]
    assert [e.secondary_text for e in per_chunk] == ["A", "b"]

    full = exporter.build_entries(chunks, asr_segments, corrected, translation_style=TranslationStyle.FULL)
    assert [e.primary_text for e in full] == ["全翻译", "全翻译"]


def test_translation_style_parse_per_segment_falls_back_to_per_chunk() -> None:
    assert TranslationStyle.parse("per_segment") == TranslationStyle.PER_CHUNK
