"""Export stage (subtitle output)."""

from __future__ import annotations

import logging
from typing import cast

from subflow.config import Settings
from subflow.exceptions import ConfigurationError
from subflow.export.subtitle_exporter import SubtitleExporter
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk
from subflow.models.subtitle_types import SubtitleExportConfig, SubtitleFormat
from subflow.pipeline.context import PipelineContext
from subflow.stages.base import Stage

logger = logging.getLogger(__name__)


class ExportStage(Stage):
    name = "export"

    def __init__(
        self,
        settings: Settings,
        format: str = "srt",
        include_secondary: bool = True,
        primary_position: str = "top",
    ) -> None:
        self.settings = settings
        self.format = format
        self.include_secondary = include_secondary
        self.primary_position = primary_position

    def validate_input(self, context: PipelineContext) -> bool:
        run_id = context.get("project_id") or context.get("job_id")
        return bool(run_id) and bool(context.get("asr_segments"))

    async def execute(self, context: PipelineContext) -> PipelineContext:
        context = cast(PipelineContext, dict(context))
        run_id = str(context.get("project_id") or context.get("job_id") or "")
        if not run_id:
            raise ConfigurationError("project_id is required")
        chunks: list[SemanticChunk] = list(context.get("semantic_chunks", []))
        asr_segments: list[ASRSegment] = list(context.get("asr_segments", []))
        asr_corrected_segments: dict[int, ASRCorrectedSegment] | None = context.get(
            "asr_corrected_segments"
        )

        fmt_raw = self.format.lower().strip()
        try:
            fmt = SubtitleFormat(fmt_raw)
        except ValueError as exc:
            raise ConfigurationError(f"Unknown subtitle format: {self.format}") from exc

        logger.info("export start (format=%s, project_id=%s)", fmt.value, run_id)
        config = SubtitleExportConfig(
            format=fmt,
            include_secondary=self.include_secondary,
            primary_position=self.primary_position,
        )
        subtitle_text = SubtitleExporter().export(
            chunks=chunks,
            asr_segments=asr_segments,
            asr_corrected_segments=asr_corrected_segments,
            config=config,
        )
        context["subtitle_text"] = subtitle_text
        context["result_path"] = f"projects/{run_id}/subtitles.{fmt.value}"
        logger.info("export done (subtitle_chars=%d)", len(subtitle_text))
        return context
