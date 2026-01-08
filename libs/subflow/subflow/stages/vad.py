"""Voice activity detection stage."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from subflow.config import Settings
from subflow.exceptions import StageExecutionError
from subflow.models.segment import VADSegment
from subflow.pipeline.context import PipelineContext
from subflow.providers import get_vad_provider
from subflow.stages.base import Stage

logger = logging.getLogger(__name__)


class VADStage(Stage):
    name = "vad"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider_name = str(settings.vad.provider or "nemo_marblenet")
        self.provider = get_vad_provider(settings.vad.model_dump())

    def validate_input(self, context: PipelineContext) -> bool:
        return bool(context.get("vocals_audio_path"))

    async def execute(self, context: PipelineContext) -> PipelineContext:
        audio_path = str(context["vocals_audio_path"])
        logger.info("vad start (audio_path=%s)", audio_path)
        try:
            timestamps = self.provider.detect(audio_path)
        except Exception as exc:
            model_path = Path(self.settings.vad.nemo_model_path)
            hint = (
                f"VAD failed (provider={self.provider_name}). "
                f"model_path={model_path} exists={model_path.exists()}. "
                "If missing, set `VAD_NEMO_MODEL_PATH` or download the NeMo `.nemo` checkpoint. "
                "If import fails, ensure `nemo_toolkit` and `torchaudio` are installed in worker env."
            )
            raise StageExecutionError(self.name, hint) from exc
        context = cast(PipelineContext, dict(context))
        context["vad_segments"] = [VADSegment(start=s, end=e) for s, e in timestamps]
        regions = getattr(self.provider, "last_regions", None)
        if isinstance(regions, list) and regions:
            context["vad_regions"] = [VADSegment(start=s, end=e) for s, e in regions]
        logger.info(
            "vad done (segments=%d, regions=%d)",
            len(context.get("vad_segments") or []),
            len(context.get("vad_regions") or []),
        )
        return context
