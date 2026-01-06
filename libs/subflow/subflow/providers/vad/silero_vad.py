"""Silero VAD provider (torch.hub)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechTimestamp:
    start: float
    end: float


class SileroVADProvider:
    def __init__(self, min_silence_duration_ms: int = 300, min_speech_duration_ms: int = 250):
        self.min_silence_duration_ms = min_silence_duration_ms
        self.min_speech_duration_ms = min_speech_duration_ms
        self._model = None
        self._utils = None

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._utils is not None:
            return
        try:
            import torch  # noqa: F401
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Silero VAD requires torch/torchaudio. "
                "Install them in the worker environment before using VAD."
            ) from exc

        import torch

        model, utils = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
        self._model = model
        self._utils = utils

    def detect(self, audio_path: str) -> list[tuple[float, float]]:
        """返回语音活动时间段 [(start, end), ...]"""
        self._ensure_loaded()
        assert self._utils is not None

        try:
            import torchaudio
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Silero VAD requires torchaudio. Install it in the worker environment."
            ) from exc

        (get_speech_timestamps, _, read_audio, _, _) = self._utils

        wav = read_audio(audio_path, sampling_rate=16000)
        speech_timestamps = get_speech_timestamps(
            wav,
            self._model,
            sampling_rate=16000,
            min_silence_duration_ms=self.min_silence_duration_ms,
            min_speech_duration_ms=self.min_speech_duration_ms,
        )

        result: list[tuple[float, float]] = []
        for item in speech_timestamps:
            start_s = float(item["start"]) / 16000.0
            end_s = float(item["end"]) / 16000.0
            result.append((start_s, end_s))
        return result
