"""VAD provider abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod


class VADProvider(ABC):
    @abstractmethod
    def detect(self, audio_path: str) -> list[tuple[float, float]]:
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover
        return None

