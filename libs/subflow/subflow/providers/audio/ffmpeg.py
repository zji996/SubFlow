"""FFmpeg-based audio utilities."""

from __future__ import annotations

import asyncio
from pathlib import Path


class FFmpegProvider:
    def __init__(self, ffmpeg_bin: str = "ffmpeg"):
        self.ffmpeg_bin = ffmpeg_bin

    async def _run(self, args: list[str]) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"ffmpeg binary not found: {self.ffmpeg_bin}. "
                "Install ffmpeg and ensure it is in PATH (or set AUDIO_FFMPEG_BIN)."
            ) from exc
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                "ffmpeg failed "
                f"(code={process.returncode}).\n"
                f"cmd: {' '.join(args)}\n"
                f"stdout: {stdout.decode(errors='ignore')}\n"
                f"stderr: {stderr.decode(errors='ignore')}"
            )

    async def extract_audio(self, video_path: str, output_path: str) -> str:
        """从视频提取音频，输出 16kHz 单声道 WAV"""
        video_path = str(video_path)
        output_path = str(output_path)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        await self._run(
            [
                self.ffmpeg_bin,
                "-y",
                "-i",
                video_path,
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                output_path,
            ]
        )
        return output_path

    async def cut_segment(self, audio_path: str, start: float, end: float, output_path: str) -> str:
        """切割音频片段"""
        audio_path = str(audio_path)
        output_path = str(output_path)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if end <= start:
            raise ValueError("end must be greater than start")

        await self._run(
            [
                self.ffmpeg_bin,
                "-y",
                "-i",
                audio_path,
                "-ss",
                str(start),
                "-to",
                str(end),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                output_path,
            ]
        )
        return output_path
