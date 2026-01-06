"""ASS subtitle formatter (minimal implementation)."""

from __future__ import annotations

from subflow.formatters.base import SubtitleFormatter
from subflow.models.segment import SemanticChunk


def _format_ass_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    cs = int(round(seconds * 100))
    c = cs % 100
    total_s = cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:d}:{m:02d}:{s:02d}.{c:02d}"


class ASSFormatter(SubtitleFormatter):
    def format(self, chunks: list[SemanticChunk]) -> str:
        header = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "Collisions: Normal",
            "PlayResX: 1920",
            "PlayResY: 1080",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,Arial,54,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,"
            "1,3,0,2,80,80,60,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        events: list[str] = []
        for chunk in chunks:
            text = (chunk.translation or chunk.text).strip().replace("\n", "\\N")
            events.append(
                "Dialogue: 0,"
                f"{_format_ass_timestamp(chunk.start)},"
                f"{_format_ass_timestamp(chunk.end)},"
                "Default,,0,0,0,,"
                f"{text}"
            )

        return "\n".join([*header, *events]).rstrip() + "\n"
