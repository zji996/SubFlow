"""Segment models for VAD/ASR and semantic processing."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VADSegment:
    start: float
    end: float
    region_id: int | None = None


@dataclass
class ASRSegment:
    id: int
    start: float
    end: float
    text: str
    language: str | None = None


@dataclass
class SentenceSegment:
    """Greedy sentence-aligned segment boundary (Stage 3 output)."""

    id: int
    start: float
    end: float
    region_id: int | None = None


@dataclass
class ASRCorrectedSegment:
    """Corrected view of an ASR segment (after applying LLM corrections)."""

    id: int
    asr_segment_id: int
    text: str


@dataclass
class ASRMergedChunk:
    """Merged ASR chunk used for Stage 4 correction (can cross VAD region boundaries)."""

    region_id: int
    chunk_id: int
    start: float
    end: float
    segment_ids: list[int] = field(default_factory=list)
    text: str = ""


@dataclass
class SegmentTranslation:
    """1:1 translation for an ASR segment (Stage 5 output)."""

    segment_id: int
    source_text: str
    translation: str


@dataclass
class TranslationChunk:
    """A translation slice mapped to exactly one ASR segment."""

    text: str
    segment_id: int


@dataclass
class SemanticChunk:
    """A semantic unit for translation."""

    id: int
    text: str  # Corrected source text
    translation: str  # Full translation (produced in Pass 2)
    asr_segment_ids: list[int] = field(default_factory=list)
    translation_chunks: list[TranslationChunk] = field(default_factory=list)
