"""Subtitle formatter base."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from subflow.models.subtitle_types import SubtitleEntry, SubtitleExportConfig


SubtitleLineKind = Literal["primary", "secondary"]


def selected_lines(
    primary: str,
    secondary: str,
    config: SubtitleExportConfig,
) -> list[tuple[SubtitleLineKind, str]]:
    primary = (primary or "").strip()
    secondary = (secondary or "").strip()
    if not primary and not secondary:
        return []

    match config.content.value:
        case "both":
            ordered: list[tuple[SubtitleLineKind, str]]
            if config.primary_position == "top":
                ordered = [("primary", primary), ("secondary", secondary)]
            else:
                ordered = [("secondary", secondary), ("primary", primary)]
            out: list[tuple[SubtitleLineKind, str]] = []
            for kind, text in ordered:
                if text:
                    out.append((kind, text))
            return out
        case "primary_only":
            return [("primary", primary)] if primary else []
        case "secondary_only":
            return [("secondary", secondary)] if secondary else []
        case _:
            raise ValueError(f"Unknown subtitle content: {config.content}")


class SubtitleFormatter(ABC):
    @abstractmethod
    def format(self, entries: list[SubtitleEntry], config: SubtitleExportConfig) -> str:
        raise NotImplementedError

    @staticmethod
    def seconds_to_timestamp(seconds: float, separator: str) -> str:
        if seconds < 0:
            seconds = 0.0
        total_ms = int(round(seconds * 1000))
        ms = total_ms % 1000
        total_s = total_ms // 1000
        s = total_s % 60
        total_m = total_s // 60
        m = total_m % 60
        h = total_m // 60
        return f"{h:02d}:{m:02d}:{s:02d}{separator}{ms:03d}"
