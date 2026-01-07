"""Demucs-based source separation utilities."""

from __future__ import annotations

from pathlib import Path

from subflow.utils.subprocess import run_subprocess


class DemucsProvider:
    def __init__(self, model: str = "htdemucs_ft", demucs_bin: str = "demucs") -> None:
        self.model = model
        self.demucs_bin = demucs_bin

    async def separate_vocals(self, audio_path: str, output_dir: str) -> str:
        """分离人声，返回 vocals.wav 路径"""
        audio_path = str(audio_path)
        output_dir = str(output_dir)
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        result = await run_subprocess(
            [
                self.demucs_bin,
                "--two-stems=vocals",
                "-n",
                self.model,
                audio_path,
                "-o",
                output_dir,
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "demucs failed "
                f"(code={result.returncode}).\n"
                f"cmd: {self.demucs_bin} --two-stems=vocals -n {self.model} {audio_path} -o {output_dir}\n"
                f"stdout: {result.stdout.decode(errors='ignore')}\n"
                f"stderr: {result.stderr.decode(errors='ignore')}"
            )

        vocals_path = Path(output_dir) / self.model / Path(audio_path).stem / "vocals.wav"
        if not vocals_path.exists():
            raise FileNotFoundError(f"demucs output not found: {vocals_path}")
        return str(vocals_path)
