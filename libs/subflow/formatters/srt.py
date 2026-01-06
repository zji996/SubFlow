"""SRT subtitle formatter."""

from __future__ import annotations

from libs.subflow.formatters.base import SubtitleFormatter
from libs.subflow.models.segment import SemanticChunk


def _format_srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class SRTFormatter(SubtitleFormatter):
    def format(self, chunks: list[SemanticChunk]) -> str:
        lines: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            text = (chunk.translation or chunk.text).strip()
            lines.append(str(index))
            lines.append(f"{_format_srt_timestamp(chunk.start)} --> {_format_srt_timestamp(chunk.end)}")
            lines.append(text)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

