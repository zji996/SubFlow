"""Audio preprocessing stage."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from subflow.config import Settings
from subflow.providers.audio import DemucsProvider, FFmpegProvider
from subflow.stages.base import Stage


class AudioPreprocessStage(Stage):
    name = "audio_preprocess"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.ffmpeg = FFmpegProvider(ffmpeg_bin=settings.audio.ffmpeg_bin)
        self.demucs = DemucsProvider(
            model=settings.audio.demucs_model,
            demucs_bin=settings.audio.demucs_bin,
        )

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("job_id")) and bool(context.get("video_url"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        job_id = str(context["job_id"])
        video_url = str(context["video_url"])

        base_dir = Path(self.settings.data_dir) / "jobs" / job_id
        base_dir.mkdir(parents=True, exist_ok=True)
        video_path = base_dir / "input_video"
        audio_path = base_dir / "audio.wav"
        demucs_out = base_dir / "demucs"

        local_video_path = context.get("video_path")
        if local_video_path and Path(str(local_video_path)).exists():
            video_path = Path(str(local_video_path))
        else:
            if Path(video_url).exists():
                video_path = Path(video_url)
            elif video_url.startswith("http://") or video_url.startswith("https://"):
                suffix = Path(video_url.split("?")[0]).suffix or ".mp4"
                video_path = base_dir / f"input{suffix}"
                async with httpx.AsyncClient() as client:
                    async with client.stream("GET", video_url, timeout=600.0) as resp:
                        resp.raise_for_status()
                        with open(video_path, "wb") as f:
                            async for chunk in resp.aiter_bytes():
                                f.write(chunk)
            else:
                raise ValueError("Unsupported video_url; provide local path or http(s) url")

        await self.ffmpeg.extract_audio(str(video_path), str(audio_path))
        vocals_path = await self.demucs.separate_vocals(str(audio_path), str(demucs_out))

        context = dict(context)
        context["video_path"] = str(video_path)
        context["audio_path"] = str(audio_path)
        context["vocals_audio_path"] = vocals_path
        return context
