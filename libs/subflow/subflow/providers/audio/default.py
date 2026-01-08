"""Default audio provider implementation (FFmpeg + Demucs)."""

from __future__ import annotations

from subflow.providers.audio.base import AudioProvider
from subflow.providers.audio.demucs import DemucsProvider
from subflow.providers.audio.ffmpeg import FFmpegProvider


class FFmpegDemucsAudioProvider(AudioProvider):
    def __init__(
        self,
        *,
        ffmpeg_bin: str = "ffmpeg",
        demucs_bin: str = "demucs",
        demucs_model: str = "htdemucs_ft",
        max_duration_s: float | None = None,
    ) -> None:
        self._ffmpeg = FFmpegProvider(ffmpeg_bin=ffmpeg_bin)
        self._demucs = DemucsProvider(model=demucs_model, demucs_bin=demucs_bin)
        self._max_duration_s = max_duration_s

    async def extract_audio(self, input_path: str, output_path: str) -> None:
        await self._ffmpeg.extract_audio(
            str(input_path),
            str(output_path),
            max_duration_s=self._max_duration_s,
        )

    async def separate_vocals(self, audio_path: str, output_dir: str) -> str:
        return await self._demucs.separate_vocals(str(audio_path), str(output_dir))

