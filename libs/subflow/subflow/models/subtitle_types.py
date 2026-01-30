"""Subtitle export models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class SubtitleEntry:
    """Single subtitle entry (supports dual-line output)."""

    index: int
    start: float  # seconds
    end: float  # seconds
    primary_text: str  # translation
    secondary_text: str  # corrected source


class SubtitleFormat(Enum):
    SRT = "srt"
    VTT = "vtt"
    ASS = "ass"
    JSON = "json"


class SubtitleContent(Enum):
    BOTH = "both"
    PRIMARY_ONLY = "primary_only"
    SECONDARY_ONLY = "secondary_only"


@dataclass(frozen=True)
class AssStyleConfig:
    """ASS style configuration for subtitle export.

    Supports two modes:
    - inline_mode=True (default): Single dialogue line with primary + \\N{\\fsXX} + secondary
    - inline_mode=False: Separate dialogue lines for primary and secondary text
    """

    # Primary (translation) style
    primary_font: str = "方正毡笔黑_GBK"
    primary_size: int = 70
    primary_color: str = "#FFFFFF"
    primary_outline_color: str = "#000000"
    primary_outline_width: int = 2

    # Secondary (source) style
    secondary_font: str = "Arial"
    secondary_size: int = 45
    secondary_color: str = "#CCCCCC"
    secondary_outline_color: str = "#000000"
    secondary_outline_width: int = 1

    # Layout
    position: str = "bottom"  # "top" | "bottom"
    margin: int = 20
    shadow_depth: int = 1

    # Mode: inline combines both texts in one dialogue line
    inline_mode: bool = True


@dataclass(frozen=True)
class SubtitleExportConfig:
    """Subtitle export configuration."""

    format: SubtitleFormat = SubtitleFormat.SRT
    content: SubtitleContent = SubtitleContent.BOTH
    primary_position: str = "top"  # "top" | "bottom"
    ass_style: AssStyleConfig | None = None
