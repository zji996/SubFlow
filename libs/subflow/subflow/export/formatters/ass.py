"""ASS subtitle formatter (dual-style or inline dual-line).

Supports two modes:
1. Dual-style mode (default): Primary and Secondary as separate dialogue lines with different styles
2. Inline mode: Single dialogue line with primary text + \\N{\\fsXX} + secondary text
"""

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
        primary_size = _safe_int(style.primary_size, default=70, min_value=8, max_value=200)
        secondary_size = _safe_int(style.secondary_size, default=45, min_value=8, max_value=200)

        primary_color = _ass_color(style.primary_color, default="&H00FFFFFF")
        secondary_color = _ass_color(style.secondary_color, default="&H00CCCCCC")
        primary_outline_color = _ass_color(style.primary_outline_color, default="&H00000000")
        secondary_outline_color = _ass_color(style.secondary_outline_color, default="&H00000000")
        outline_width = _safe_int(
            style.primary_outline_width, default=2, min_value=0, max_value=10
        )
        shadow_depth = _safe_int(getattr(style, "shadow_depth", 1), default=1, min_value=0, max_value=10)

        primary_font = (style.primary_font or "Arial").replace(",", " ").strip() or "Arial"
        secondary_font = (style.secondary_font or "Arial").replace(",", " ").strip() or "Arial"

        # Check if inline mode is enabled (single line with \N{\fsXX} separator)
        inline_mode = getattr(style, "inline_mode", True)  # Default to inline mode

        # ASS V4+ Style format (complete spec):
        # Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,
        #         Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,
        #         BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
        header = f"""[Script Info]
Title: SubFlow Generated Subtitles
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{primary_font},{primary_size},{primary_color},{secondary_color},{primary_outline_color},&H80000000,0,0,0,0,100,100,0,0,1,{outline_width},{shadow_depth},{alignment},10,10,{base_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        events: list[str] = []

        for entry in entries:
            start = _seconds_to_ass_time(entry.start)
            end = _seconds_to_ass_time(entry.end)

            # Process primary text: replace Chinese comma with space for better readability
            primary_text = (entry.primary_text or "").strip()
            primary_text = primary_text.replace("，", " ").replace("\n", "\\N")

            secondary_text = (entry.secondary_text or "").strip().replace("\n", "\\N")

            if inline_mode and config.content.value == "both":
                # Inline mode: combine primary + secondary with font size override
                # Format: 中文翻译 \N{\fs45}English source
                if primary_text and secondary_text:
                    # Primary text first (uses style's default font size)
                    # Secondary text with explicit font size override
                    combined = f"{primary_text} \\N{{\\fs{secondary_size}}}{secondary_text}"
                    events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{combined}")
                elif primary_text:
                    events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{primary_text}")
                elif secondary_text:
                    events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{secondary_text}")
            else:
                # Legacy dual-style mode (separate lines for primary/secondary)
                rendered = [
                    (kind, text.replace("\n", "\\N"))
                    for kind, text in selected_lines(entry.primary_text, entry.secondary_text, config)
                ]
                if not rendered:
                    continue

                for kind, text in rendered:
                    events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

        return (header + "\n".join(events)).rstrip() + "\n"
