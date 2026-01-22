"""Voice activity detection stage."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from subflow.config import Settings
from subflow.exceptions import StageExecutionError
from subflow.models.segment import VADSegment
from subflow.pipeline.context import PipelineContext, ProgressReporter
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

    async def execute(
        self,
        context: PipelineContext,
        progress_reporter: ProgressReporter | None = None,
    ) -> PipelineContext:
        audio_path = str(context["vocals_audio_path"])
        logger.info("vad start (audio_path=%s)", audio_path)
        try:
            frame_probs = None
            detect_with_probs = getattr(self.provider, "detect_with_probs", None)
            if callable(detect_with_probs):
                timestamps, frame_probs = detect_with_probs(audio_path)
            else:
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
        # Stage 3 now does sentence-aligned splitting, so keep VAD output coarse by default.
        # Consumers should prefer `vad_regions`; `vad_segments` is a legacy alias (read-only fallback).
        regions = getattr(self.provider, "last_regions", None)
        vad_regions = (
            [VADSegment(start=s, end=e) for s, e in regions]
            if isinstance(regions, list) and regions
            else [VADSegment(start=s, end=e) for s, e in timestamps]
        )
        context["vad_regions"] = vad_regions

        if frame_probs is not None:
            context["vad_frame_probs"] = frame_probs
            context["vad_frame_hop_s"] = float(getattr(self.provider, "frame_hop_s", 0.02))
        logger.info(
            "vad done (regions=%d, frame_probs=%s)",
            len(context.get("vad_regions") or []),
            "yes" if context.get("vad_frame_probs") is not None else "no",
        )
        return context
