"""Audio preprocessing stage (mock implementation)."""

from __future__ import annotations

from typing import Any

from libs.subflow.config import Settings
from libs.subflow.stages.base import Stage


class AudioPreprocessStage(Stage):
    name = "audio_preprocess"

    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("job_id")) and bool(context.get("video_url"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        job_id = str(context["job_id"])
        data_dir = self.settings.data_dir.rstrip("/")
        context = dict(context)
        context["vocals_audio_path"] = f"{data_dir}/jobs/{job_id}/vocals.wav"
        return context

