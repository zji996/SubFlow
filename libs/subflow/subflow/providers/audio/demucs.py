"""Demucs-based source separation utilities."""

from __future__ import annotations

import asyncio
from pathlib import Path


class DemucsProvider:
    def __init__(self, model: str = "htdemucs_ft", demucs_bin: str = "demucs"):
        self.model = model
        self.demucs_bin = demucs_bin

    async def separate_vocals(self, audio_path: str, output_dir: str) -> str:
        """分离人声，返回 vocals.wav 路径"""
        audio_path = str(audio_path)
        output_dir = str(output_dir)
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        try:
            process = await asyncio.create_subprocess_exec(
                self.demucs_bin,
                "--two-stems=vocals",
                "-n",
                self.model,
                audio_path,
                "-o",
                output_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"demucs binary not found: {self.demucs_bin}. "
                "Install demucs in the worker env (e.g. `uv add --project apps/worker demucs`) "
                "or set AUDIO_DEMUCS_BIN."
            ) from exc
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                "demucs failed "
                f"(code={process.returncode}).\n"
                f"cmd: {self.demucs_bin} --two-stems=vocals -n {self.model} {audio_path} -o {output_dir}\n"
                f"stdout: {stdout.decode(errors='ignore')}\n"
                f"stderr: {stderr.decode(errors='ignore')}"
            )

        vocals_path = Path(output_dir) / self.model / Path(audio_path).stem / "vocals.wav"
        if not vocals_path.exists():
            raise FileNotFoundError(f"demucs output not found: {vocals_path}")
        return str(vocals_path)
