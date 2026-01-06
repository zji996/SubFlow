"""Subtitle formatter base."""

from __future__ import annotations

from abc import ABC, abstractmethod

from subflow.models.subtitle_types import SubtitleEntry, SubtitleExportConfig


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

