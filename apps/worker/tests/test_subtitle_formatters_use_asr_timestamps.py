from __future__ import annotations

from subflow.export import SubtitleExporter
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk
from subflow.models.subtitle_types import SubtitleExportConfig, SubtitleFormat


def test_srt_export_uses_asr_segment_timestamps_and_dual_line() -> None:
    chunks = [
        SemanticChunk(
            id=0,
            text="hello",
            translation="你好",
            asr_segment_ids=[2, 3],
        )
    ]
    asr_segments = [
        ASRSegment(id=2, start=1.2, end=3.6, text="hello"),
        ASRSegment(id=3, start=3.6, end=5.0, text="world"),
    ]
    corrected = {
        2: ASRCorrectedSegment(id=2, asr_segment_id=2, text="hello"),
        3: ASRCorrectedSegment(id=3, asr_segment_id=3, text="world"),
    }

    out = SubtitleExporter().export(
        chunks=chunks,
        asr_segments=asr_segments,
        asr_corrected_segments=corrected,
        config=SubtitleExportConfig(format=SubtitleFormat.SRT, include_secondary=True, primary_position="top"),
    )
    assert "00:00:01,200 --> 00:00:03,600" in out
    assert "00:00:03,600 --> 00:00:05,000" in out
    assert "你好" in out
    assert "hello" in out
    assert "world" in out


def test_srt_export_includes_filler_as_secondary_only() -> None:
    chunks = [
        SemanticChunk(id=0, text="hello world", translation="你好世界", asr_segment_ids=[2, 3]),
    ]
    asr_segments = [
        ASRSegment(id=0, start=0.0, end=1.2, text="嗯"),
        ASRSegment(id=1, start=1.2, end=2.0, text="那个"),
        ASRSegment(id=2, start=2.0, end=3.6, text="hello"),
        ASRSegment(id=3, start=3.6, end=5.0, text="world"),
    ]
    corrected = {
        0: ASRCorrectedSegment(id=0, asr_segment_id=0, text="嗯"),
        1: ASRCorrectedSegment(id=1, asr_segment_id=1, text="那个"),
        2: ASRCorrectedSegment(id=2, asr_segment_id=2, text="hello"),
        3: ASRCorrectedSegment(id=3, asr_segment_id=3, text="world"),
    }

    out = SubtitleExporter().export(
        chunks=chunks,
        asr_segments=asr_segments,
        asr_corrected_segments=corrected,
        config=SubtitleExportConfig(format=SubtitleFormat.SRT, include_secondary=True, primary_position="top"),
    )
    assert "00:00:00,000 --> 00:00:01,200" in out
    assert "00:00:01,200 --> 00:00:02,000" in out
    assert "嗯" in out
    assert "那个" in out
    assert "00:00:02,000 --> 00:00:03,600" in out
    assert "00:00:03,600 --> 00:00:05,000" in out
