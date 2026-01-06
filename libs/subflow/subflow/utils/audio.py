"""Audio utilities (FFmpeg helpers)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path


async def cut_audio_segment(
    input_path: str,
    output_path: str,
    start: float,
    end: float,
    ffmpeg_bin: str = "ffmpeg",
) -> None:
    """使用 ffmpeg 切割音频片段（输出 16kHz 单声道 WAV）"""
    if end <= start:
        raise ValueError("end must be greater than start")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        input_path,
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
        str(output),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    rc = await proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg cut failed (code={rc}): {' '.join(cmd)}")


async def cut_audio_segments_batch(
    input_path: str,
    segments: list[tuple[float, float]],
    output_dir: str,
    max_concurrent: int = 10,
    ffmpeg_bin: str = "ffmpeg",
) -> list[str]:
    """批量切割音频，返回输出路径列表"""
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(max(1, int(max_concurrent)))

    async def _one(index: int, start: float, end: float) -> str:
        async with semaphore:
            out = output_dir_path / f"segment_{index:04d}.wav"
            await cut_audio_segment(
                input_path=input_path,
                output_path=str(out),
                start=start,
                end=end,
                ffmpeg_bin=ffmpeg_bin,
            )
            return str(out)

    tasks = [_one(i, float(s), float(e)) for i, (s, e) in enumerate(segments)]
    return list(await asyncio.gather(*tasks))


def cleanup_segment_files(paths: list[str]) -> None:
    for path in paths:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass
