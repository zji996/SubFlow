"""Voice activity detection stage (mock implementation)."""

from __future__ import annotations

from typing import Any

from libs.subflow.config import Settings
from libs.subflow.models.segment import VADSegment
from libs.subflow.stages.base import Stage


class VADStage(Stage):
    name = "vad"

    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("vocals_audio_path"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        context = dict(context)
        context["vad_segments"] = [VADSegment(start=0.0, end=10.0)]
        return context

