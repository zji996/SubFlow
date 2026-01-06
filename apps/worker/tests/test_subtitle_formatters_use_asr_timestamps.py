from __future__ import annotations

from subflow.formatters.srt import SRTFormatter
from subflow.models.segment import ASRSegment, SemanticChunk


def test_srt_formatter_uses_asr_segment_timestamps() -> None:
    chunks = [
        SemanticChunk(
            id=0,
            text="hello",
            translation="你好",
            asr_segment_ids=[2, 3],
        )
    ]
    asr_segments = {
        2: ASRSegment(id=2, start=1.2, end=3.6, text="hello"),
        3: ASRSegment(id=3, start=3.6, end=5.0, text="world"),
    }

    out = SRTFormatter().format(chunks, asr_segments)
    assert "00:00:01,200 --> 00:00:05,000" in out
    assert "你好" in out

