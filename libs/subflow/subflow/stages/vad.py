"""Voice activity detection stage."""

from __future__ import annotations

from typing import Any

from subflow.config import Settings
from subflow.models.segment import VADSegment
from subflow.providers.vad import SileroVADProvider
from subflow.stages.base import Stage


class VADStage(Stage):
    name = "vad"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider = SileroVADProvider(
            min_silence_duration_ms=settings.vad.min_silence_duration_ms,
            min_speech_duration_ms=settings.vad.min_speech_duration_ms,
        )

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("vocals_audio_path"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        timestamps = self.provider.detect(str(context["vocals_audio_path"]))
        context = dict(context)
        context["vad_segments"] = [VADSegment(start=s, end=e) for s, e in timestamps]
        return context
