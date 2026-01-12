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


class TranslationStyle(Enum):
    """How to display translations for multi-segment chunks."""

    FULL = "full"  # Each segment shows the full chunk translation
    PER_CHUNK = "per_chunk"  # Each segment shows its assigned chunk translation

    @classmethod
    def parse(cls, value: str) -> TranslationStyle:
        """Parse style with backward-compatible fallback.

        `per_segment` was a legacy style; it is treated as `per_chunk`.
        """

        normalized = str(value or "").strip().lower()
        if normalized == "per_segment":
            normalized = cls.PER_CHUNK.value
        return cls(normalized)


@dataclass(frozen=True)
class AssStyleConfig:
    primary_font: str = "思源黑体"
    primary_size: int = 36
    primary_color: str = "#FFFFFF"
    primary_outline_color: str = "#000000"
    primary_outline_width: int = 2

    secondary_font: str = "Arial"
    secondary_size: int = 24
    secondary_color: str = "#CCCCCC"
    secondary_outline_color: str = "#000000"
    secondary_outline_width: int = 1

    position: str = "bottom"  # "top" | "bottom"
    margin: int = 20


@dataclass(frozen=True)
class SubtitleExportConfig:
    """Subtitle export configuration."""

    format: SubtitleFormat = SubtitleFormat.SRT
    content: SubtitleContent = SubtitleContent.BOTH
    primary_position: str = "top"  # "top" | "bottom"
    translation_style: TranslationStyle = (
        TranslationStyle.PER_CHUNK
    )  # Default: distribute by translation_chunks
    ass_style: AssStyleConfig | None = None
