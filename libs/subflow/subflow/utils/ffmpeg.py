"""FFmpeg binary resolution helper.

Prefer system `ffmpeg`, fallback to `imageio-ffmpeg` bundled binary (uv-friendly).
"""

from __future__ import annotations

import shutil
from pathlib import Path


def resolve_ffmpeg_bin(ffmpeg_bin: str = "ffmpeg") -> str:
    ffmpeg_bin = (ffmpeg_bin or "ffmpeg").strip()

    if Path(ffmpeg_bin).exists():
        return ffmpeg_bin

    found = shutil.which(ffmpeg_bin)
    if found:
        return found

    try:
        import imageio_ffmpeg  # type: ignore

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return ffmpeg_bin

