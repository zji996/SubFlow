"""Export stage (mock implementation)."""

from __future__ import annotations

from typing import Any

from subflow.config import Settings
from subflow.models.segment import SemanticChunk
from subflow.stages.base import Stage


class ExportStage(Stage):
    name = "export"

    def __init__(self, settings: Settings, format: str = "srt"):
        self.settings = settings
        self.format = format

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("job_id")) and bool(context.get("semantic_chunks"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        context = dict(context)
        job_id = str(context["job_id"])
        chunks: list[SemanticChunk] = list(context.get("semantic_chunks", []))

        formatter_name = self.format.lower()
        match formatter_name:
            case "srt":
                from subflow.formatters.srt import SRTFormatter

                formatter = SRTFormatter()
            case "vtt":
                from subflow.formatters.vtt import VTTFormatter

                formatter = VTTFormatter()
            case "ass":
                from subflow.formatters.ass import ASSFormatter

                formatter = ASSFormatter()
            case _:
                raise ValueError(f"Unknown subtitle format: {self.format}")

        subtitle_text = formatter.format(chunks)
        context["subtitle_text"] = subtitle_text
        context["result_path"] = f"jobs/{job_id}/subtitles.{formatter_name}"
        return context
