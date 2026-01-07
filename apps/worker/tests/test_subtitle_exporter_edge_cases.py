from __future__ import annotations

from subflow.export.subtitle_exporter import SubtitleExporter
from subflow.models.segment import ASRCorrectedSegment, ASRSegment
from subflow.models.subtitle_types import SubtitleExportConfig, SubtitleFormat


def test_exporter_handles_empty_chunks_by_falling_back_to_asr_segments() -> None:
    exporter = SubtitleExporter()
    asr_segments = [
        ASRSegment(id=0, start=0.0, end=1.0, text="Hello"),
        ASRSegment(id=1, start=1.0, end=2.0, text="World"),
    ]
    out = exporter.export(
        chunks=[],
        asr_segments=asr_segments,
        asr_corrected_segments=None,
        config=SubtitleExportConfig(format=SubtitleFormat.SRT),
    )
    assert "Hello" in out
    assert "World" in out


def test_exporter_prefers_corrected_text_for_secondary() -> None:
    exporter = SubtitleExporter()
    asr_segments = [
        ASRSegment(id=0, start=0.0, end=1.0, text="Helo"),
        ASRSegment(id=1, start=1.0, end=2.0, text="Wrold"),
    ]
    corrected = {
        0: ASRCorrectedSegment(id=0, asr_segment_id=0, text="Hello"),
        1: ASRCorrectedSegment(id=1, asr_segment_id=1, text="World"),
    }
    out = exporter.export(
        chunks=[],
        asr_segments=asr_segments,
        asr_corrected_segments=corrected,
        config=SubtitleExportConfig(format=SubtitleFormat.SRT, include_secondary=True),
    )
    assert "Hello" in out
    assert "World" in out
    assert "Helo" not in out
    assert "Wrold" not in out
