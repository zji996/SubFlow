"""Subtitle formatter base."""

from __future__ import annotations

from abc import ABC, abstractmethod

from subflow.models.segment import ASRSegment, SemanticChunk


class SubtitleFormatter(ABC):
    @abstractmethod
    def format(self, chunks: list[SemanticChunk], asr_segments: dict[int, ASRSegment]) -> str:
        ...
