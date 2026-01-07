"""ASS subtitle formatter (dual-style)."""

from __future__ import annotations

from subflow.export.formatters.base import SubtitleFormatter, selected_lines
from subflow.models.subtitle_types import AssStyleConfig, SubtitleEntry, SubtitleExportConfig


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


def _ass_color(value: str, *, default: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return default
    if raw.startswith("&H") and len(raw) >= 4:
        return raw
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) != 6:
        return default
    try:
        r = int(raw[0:2], 16)
        g = int(raw[2:4], 16)
        b = int(raw[4:6], 16)
    except ValueError:
        return default
    return f"&H00{b:02X}{g:02X}{r:02X}"


def _safe_int(value: int, *, default: int, min_value: int = 0, max_value: int = 10_000) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, v))


class ASSFormatter(SubtitleFormatter):
    def format(self, entries: list[SubtitleEntry], config: SubtitleExportConfig) -> str:
        style = config.ass_style or AssStyleConfig()
        position = (style.position or "bottom").strip().lower()
        if position not in {"top", "bottom"}:
            position = "bottom"
        alignment = 8 if position == "top" else 2
        base_margin = _safe_int(style.margin, default=20, min_value=0, max_value=200)
        primary_size = _safe_int(style.primary_size, default=36, min_value=8, max_value=200)
        secondary_size = _safe_int(style.secondary_size, default=24, min_value=8, max_value=200)
        spacing = max(primary_size, secondary_size) + 10

        if position == "bottom":
            above_margin = base_margin + spacing
            below_margin = base_margin
        else:
            above_margin = base_margin
            below_margin = base_margin + spacing

        if config.primary_position == "top":
            primary_margin = above_margin
            secondary_margin = below_margin
        else:
            primary_margin = below_margin
            secondary_margin = above_margin

        primary_color = _ass_color(style.primary_color, default="&H00FFFFFF")
        secondary_color = _ass_color(style.secondary_color, default="&H00CCCCCC")
        primary_outline_color = _ass_color(style.primary_outline_color, default="&H00000000")
        secondary_outline_color = _ass_color(style.secondary_outline_color, default="&H00000000")
        primary_outline_width = _safe_int(style.primary_outline_width, default=2, min_value=0, max_value=10)
        secondary_outline_width = _safe_int(style.secondary_outline_width, default=1, min_value=0, max_value=10)

        header = """[Script Info]
Title: SubFlow Generated Subtitles
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, OutlineColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Primary,{primary_font},{primary_size},{primary_color},&H00000000,{primary_outline_color},0,0,1,{primary_outline_width},1,{alignment},10,10,{primary_margin},1
Style: Secondary,{secondary_font},{secondary_size},{secondary_color},&H00000000,{secondary_outline_color},0,0,1,{secondary_outline_width},1,{alignment},10,10,{secondary_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(
            primary_font=(style.primary_font or "Arial").replace(",", " ").strip() or "Arial",
            primary_size=primary_size,
            primary_color=primary_color,
            primary_outline_color=primary_outline_color,
            primary_outline_width=primary_outline_width,
            alignment=alignment,
            primary_margin=primary_margin,
            secondary_font=(style.secondary_font or "Arial").replace(",", " ").strip() or "Arial",
            secondary_size=secondary_size,
            secondary_color=secondary_color,
            secondary_outline_color=secondary_outline_color,
            secondary_outline_width=secondary_outline_width,
            secondary_margin=secondary_margin,
        )
        events: list[str] = []

        for entry in entries:
            rendered = [
                (kind, text.replace("\n", "\\N"))
                for kind, text in selected_lines(entry.primary_text, entry.secondary_text, config)
            ]
            if not rendered:
                continue

            start = _seconds_to_ass_time(entry.start)
            end = _seconds_to_ass_time(entry.end)

            for kind, text in rendered:
                style_name = "Primary" if kind == "primary" else "Secondary"
                events.append(f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}")

        return (header + "\n".join(events)).rstrip() + "\n"
