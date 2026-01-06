"""ASS subtitle formatter (dual-style)."""

from __future__ import annotations

from subflow.export.formatters.base import SubtitleFormatter
from subflow.models.subtitle_types import SubtitleEntry, SubtitleExportConfig


def _seconds_to_ass_time(seconds: float) -> str:
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
    def format(self, entries: list[SubtitleEntry], config: SubtitleExportConfig) -> str:
        header = """[Script Info]
Title: SubFlow Generated Subtitles
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, OutlineColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Primary,Arial,48,&H00FFFFFF,&H00000000,&H00000000,0,0,1,2,1,2,10,10,50,1
Style: Secondary,Arial,36,&H00CCCCCC,&H00000000,&H00000000,0,0,1,1,1,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events: list[str] = []

        for entry in entries:
            primary = (entry.primary_text or "").strip().replace("\n", "\\N")
            secondary = (entry.secondary_text or "").strip().replace("\n", "\\N")
            if not primary and not secondary:
                continue

            start = _seconds_to_ass_time(entry.start)
            end = _seconds_to_ass_time(entry.end)

            include_secondary = config.include_secondary or (not primary and bool(secondary))

            if config.primary_position == "top":
                primary_style = "Primary"
                secondary_style = "Secondary"
            else:
                primary_style = "Secondary"
                secondary_style = "Primary"

            if primary:
                events.append(f"Dialogue: 0,{start},{end},{primary_style},,0,0,0,,{primary}")
            if include_secondary and secondary:
                events.append(f"Dialogue: 0,{start},{end},{secondary_style},,0,0,0,,{secondary}")

        return (header + "\n".join(events)).rstrip() + "\n"

