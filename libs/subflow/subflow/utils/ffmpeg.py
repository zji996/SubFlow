"""FFmpeg binary resolution helper.

Prefer system `ffmpeg`, fallback to `imageio-ffmpeg` bundled binary (uv-friendly).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def resolve_ffmpeg_bin(ffmpeg_bin: str = "ffmpeg") -> str:
    ffmpeg_bin = (ffmpeg_bin or "ffmpeg").strip()

    if Path(ffmpeg_bin).exists():
        return ffmpeg_bin

    found = shutil.which(ffmpeg_bin)
    if found:
        return found

    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception as exc:
        logger.warning("failed to resolve bundled ffmpeg (%s); fallback to %r", exc, ffmpeg_bin)
        return ffmpeg_bin
