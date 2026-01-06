"""Subtitle formatter base."""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.subflow.models.segment import SemanticChunk


class SubtitleFormatter(ABC):
    @abstractmethod
    def format(self, chunks: list[SemanticChunk]) -> str:
        ...

