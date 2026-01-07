"""Audio preprocessing stage."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import cast

import httpx

from subflow.config import Settings
from subflow.exceptions import ConfigurationError, StageExecutionError
from subflow.pipeline.context import PipelineContext
from subflow.providers.audio import DemucsProvider, FFmpegProvider
from subflow.stages.base import Stage

logger = logging.getLogger(__name__)


class AudioPreprocessStage(Stage):
    name = "audio_preprocess"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ffmpeg = FFmpegProvider(ffmpeg_bin=settings.audio.ffmpeg_bin)
        self.demucs = DemucsProvider(
            model=settings.audio.demucs_model,
            demucs_bin=settings.audio.demucs_bin,
        )

    def validate_input(self, context: PipelineContext) -> bool:
        run_id = context.get("project_id") or context.get("job_id")
        media_url = context.get("media_url") or context.get("video_url")
        return bool(run_id) and bool(media_url)

    async def execute(self, context: PipelineContext) -> PipelineContext:
        run_id = str(context.get("project_id") or context.get("job_id") or "")
        media_url = str(context.get("media_url") or context.get("video_url") or "")
        if not run_id or not media_url:
            raise ConfigurationError("project_id/media_url is required")

        logger.info("audio_preprocess start (project_id=%s)", run_id)

        base_dir = Path(self.settings.data_dir) / "projects" / run_id
        base_dir.mkdir(parents=True, exist_ok=True)
        video_path = base_dir / "input_video"
        audio_path = base_dir / "audio.wav"
        demucs_out = base_dir / "demucs"

        local_video_path = context.get("video_path")
        if local_video_path and Path(str(local_video_path)).exists():
            video_path = Path(str(local_video_path))
            logger.debug("use local video_path=%s", video_path)
        else:
            if Path(media_url).exists():
                video_path = Path(media_url)
                logger.debug("use file media_url=%s", video_path)
            elif media_url.startswith("http://") or media_url.startswith("https://"):
                suffix = Path(media_url.split("?")[0]).suffix or ".mp4"
                video_path = base_dir / f"input{suffix}"
                try:
                    async with httpx.AsyncClient() as client:
                        async with client.stream("GET", media_url, timeout=600.0) as resp:
                            resp.raise_for_status()
                            with open(video_path, "wb") as f:
                                async for chunk in resp.aiter_bytes():
                                    f.write(chunk)
                except httpx.HTTPError as exc:
                    logger.exception("download failed (media_url=%s)", media_url)
                    raise StageExecutionError(self.name, f"download failed: {exc}") from exc
                logger.info("downloaded media_url to %s", video_path)
            else:
                raise ConfigurationError("Unsupported media_url; provide local path or http(s) url")

        await self.ffmpeg.extract_audio(
            str(video_path),
            str(audio_path),
            max_duration_s=self.settings.audio.max_duration_s,
        )
        logger.info("extracted audio to %s", audio_path)

        try:
            vocals_path = await self.demucs.separate_vocals(str(audio_path), str(demucs_out))
        except Exception as exc:
            logger.exception("demucs separation failed")
            raise StageExecutionError(
                self.name,
                "Demucs separation failed. Demucs is required. "
                "Ensure `demucs` is installed in the worker uv env and runnable, and set "
                "`CUDA_VISIBLE_DEVICES=1` if GPU0 is occupied."
            ) from exc

        context = cast(PipelineContext, dict(context))
        context["video_path"] = str(video_path)
        context["audio_path"] = str(audio_path)
        context["vocals_audio_path"] = vocals_path
        logger.info("audio_preprocess done (vocals_audio_path=%s)", vocals_path)
        return context
