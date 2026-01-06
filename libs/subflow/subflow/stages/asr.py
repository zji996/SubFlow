"""ASR stage with real GLM-ASR provider integration."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from subflow.config import Settings
from subflow.models.segment import ASRSegment, VADSegment
from subflow.providers.asr.glm_asr import GLMASRProvider
from subflow.stages.base import Stage
from subflow.utils.audio import cleanup_segment_files, cut_audio_segments_batch


class ASRStage(Stage):
    """ASR stage that transcribes VAD segments using GLM-ASR."""

    name = "asr"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider = GLMASRProvider(
            base_url=settings.asr.base_url,
            model=settings.asr.model,
            api_key=settings.asr.api_key or "abc123",
            max_concurrent=settings.asr.max_concurrent,
            timeout=settings.asr.timeout,
        )

    def validate_input(self, context: dict[str, Any]) -> bool:
        """Check that vocals audio and VAD segments exist."""
        return bool(context.get("vocals_audio_path")) and bool(context.get("vad_segments"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute ASR on all VAD segments concurrently.

        Input context keys:
            - vocals_audio_path: Path to the vocals audio file
            - vad_segments: List of VADSegment objects

        Output context keys (added):
            - asr_segments: List of ASRSegment objects
            - full_transcript: Complete transcript text
            - source_language: Detected or specified source language
        """
        context = dict(context)
        vocals_path: str = context["vocals_audio_path"]
        vad_segments: list[VADSegment] = context["vad_segments"]
        source_language = context.get("source_language") or None

        if not vad_segments:
            context["asr_segments"] = []
            context["full_transcript"] = ""
            return context

        # Create temp directory for audio segments
        job_id = context.get("job_id", "unknown")
        temp_dir = Path(tempfile.gettempdir()) / "subflow" / job_id / "asr_segments"

        try:
            # 1. Cut audio into segments (concurrent ffmpeg)
            time_ranges = [(seg.start, seg.end) for seg in vad_segments]
            segment_paths = await cut_audio_segments_batch(
                input_path=vocals_path,
                segments=time_ranges,
                output_dir=str(temp_dir),
                max_concurrent=10,  # FFmpeg 并发数
            )

            # 2. Transcribe all segments concurrently
            texts = await self.provider.transcribe_batch(segment_paths, language=source_language)

            # 3. Assemble results with timing
            asr_segments: list[ASRSegment] = []
            for i, (vad_seg, text) in enumerate(zip(vad_segments, texts)):
                asr_segments.append(
                    ASRSegment(
                        id=i,
                        start=vad_seg.start,
                        end=vad_seg.end,
                        text=text.strip(),
                        language=source_language,
                    )
                )

            # 4. Build full transcript
            full_transcript = " ".join(seg.text for seg in asr_segments if seg.text)

            context["asr_segments"] = asr_segments
            context["full_transcript"] = full_transcript
            context["source_language"] = source_language

        finally:
            # 5. Cleanup temporary segment files
            if temp_dir.exists():
                cleanup_segment_files([str(p) for p in temp_dir.glob("*.wav")])
                try:
                    temp_dir.rmdir()
                except OSError:
                    pass

        return context

    async def close(self) -> None:
        """Release provider resources."""
        await self.provider.close()
