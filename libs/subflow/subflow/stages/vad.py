"""Voice activity detection stage."""

from __future__ import annotations

import logging

from subflow.config import Settings
from subflow.models.segment import VADSegment
from subflow.pipeline.context import PipelineContext
from subflow.providers.vad import NemoMarbleNetVADProvider
from subflow.stages.base import Stage

logger = logging.getLogger(__name__)


class VADStage(Stage):
    name = "vad"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider_name = "nemo"
        self.provider = NemoMarbleNetVADProvider(
            model_path=settings.vad.nemo_model_path,
            threshold=settings.vad.threshold,
            min_silence_duration_ms=settings.vad.min_silence_duration_ms,
            min_speech_duration_ms=settings.vad.min_speech_duration_ms,
            target_max_segment_s=settings.vad.target_max_segment_s,
            split_threshold=settings.vad.split_threshold,
            split_search_backtrack_ratio=settings.vad.split_search_backtrack_ratio,
            split_search_forward_ratio=settings.vad.split_search_forward_ratio,
            split_gap_s=settings.vad.split_gap_s,
            device=settings.vad.nemo_device,
        )

    def validate_input(self, context: PipelineContext) -> bool:
        return bool(context.get("vocals_audio_path"))

    async def execute(self, context: PipelineContext) -> PipelineContext:
        audio_path = str(context["vocals_audio_path"])
        # NeMo is the only supported VAD backend now; errors should be explicit.
        logger.info("vad start (audio_path=%s)", audio_path)
        timestamps = self.provider.detect(audio_path)
        context = dict(context)
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
