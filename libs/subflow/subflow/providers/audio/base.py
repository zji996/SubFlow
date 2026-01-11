"""Audio provider abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod


class AudioProvider(ABC):
    @abstractmethod
    async def extract_audio(self, input_path: str, output_path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def separate_vocals(self, audio_path: str, output_dir: str) -> str:
        raise NotImplementedError

    async def normalize_audio(self, input_path: str, output_path: str, *, target_db: float = -1.0) -> str:
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover
        return None
