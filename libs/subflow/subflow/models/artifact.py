"""Artifact model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ArtifactType(Enum):
    VOCALS_AUDIO = "vocals_audio"
    VAD_SEGMENTS = "vad_segments"
    ASR_RESULTS = "asr_results"
    FULL_TRANSCRIPT = "full_transcript"
    GLOBAL_CONTEXT = "global_context"
    SEMANTIC_CHUNKS = "semantic_chunks"
    TRANSLATION = "translation"
    SUBTITLE_FILE = "subtitle_file"


@dataclass
class Artifact:
    job_id: str
    type: ArtifactType
    path: str  # S3 path
    metadata: dict[str, Any] = field(default_factory=dict)
