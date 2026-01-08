"""ASR Provider base class."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ASRSegment:
    """A transcribed segment with timing information."""

    text: str
    start: float
    end: float
    language: str | None = None
    confidence: float | None = None


class ASRProvider(ABC):
    """Abstract base class for ASR providers."""

    @abstractmethod
    async def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
    ) -> list[ASRSegment]:
        """Transcribe an audio file.

        Args:
            audio_path: Path to the audio file.
            language: Optional language hint.

        Returns:
            List of transcribed segments with timing.
        """
        ...

    @abstractmethod
    async def transcribe_segment(
        self,
        audio_path: str,
        start: float,
        end: float,
    ) -> str:
        """Transcribe a specific time range.

        Args:
            audio_path: Path to the audio file.
            start: Start time in seconds.
            end: End time in seconds.

        Returns:
            Transcribed text.
        """
        ...

    async def close(self) -> None:  # pragma: no cover
        return None
