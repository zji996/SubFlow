"""Export stage (subtitle output)."""

from __future__ import annotations

import logging
from typing import cast

from subflow.config import Settings
from subflow.exceptions import ConfigurationError
from subflow.export.subtitle_exporter import SubtitleExporter
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk
from subflow.models.subtitle_types import (
    SubtitleContent,
    SubtitleExportConfig,
    SubtitleFormat,
    TranslationStyle,
)
from subflow.pipeline.context import PipelineContext, ProgressReporter
from subflow.stages.base import Stage

logger = logging.getLogger(__name__)


class ExportStage(Stage):
    name = "export"

    def __init__(
        self,
        settings: Settings,
        format: str = "srt",
        content: str = "both",
        primary_position: str = "top",
        translation_style: str = "per_chunk",
    ) -> None:
        self.settings = settings
        self.format = format
        self.content = content
        self.primary_position = primary_position
        self.translation_style = translation_style

    def validate_input(self, context: PipelineContext) -> bool:
        run_id = context.get("project_id") or context.get("job_id")
        return bool(run_id) and bool(context.get("asr_segments"))

    async def execute(
        self,
        context: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> PipelineContext:
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

        content_raw = self.content.lower().strip()
        try:
            content = SubtitleContent(content_raw)
        except ValueError as exc:
            raise ConfigurationError(f"Unknown subtitle content: {self.content}") from exc

        style_raw = self.translation_style.lower().strip()
        try:
            translation_style = TranslationStyle.parse(style_raw)
        except ValueError as exc:
            raise ConfigurationError(
                f"Unknown translation style: {self.translation_style}"
            ) from exc

        logger.info(
            "export start (format=%s, translation_style=%s, project_id=%s)",
            fmt.value,
            translation_style.value,
            run_id,
        )
        config = SubtitleExportConfig(
            format=fmt,
            content=content,
            primary_position=self.primary_position,
            translation_style=translation_style,
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
