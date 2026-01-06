"""ASR stage (mock implementation)."""

from __future__ import annotations

from typing import Any

from libs.subflow.config import Settings
from libs.subflow.models.segment import ASRSegment
from libs.subflow.stages.base import Stage


class ASRStage(Stage):
    name = "asr"

    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("vocals_audio_path")) and bool(context.get("vad_segments"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        context = dict(context)
        segments = [
            ASRSegment(id=1, start=0.0, end=5.0, text="Hello world", language="en"),
            ASRSegment(id=2, start=5.0, end=10.0, text="This is SubFlow", language="en"),
        ]
        context["asr_segments"] = segments
        context["full_transcript"] = " ".join(s.text for s in segments)
        context.setdefault("source_language", "en")
        return context

