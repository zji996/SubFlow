"""GLM-ASR Provider implementation with concurrent support."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

from subflow.exceptions import ProviderError
from subflow.providers.asr.base import ASRProvider, ASRSegment

logger = logging.getLogger(__name__)


class GLMASRProvider(ASRProvider):
    """GLM-ASR API provider via vLLM OpenAI-compatible interface.

    Supports concurrent transcription requests with connection pooling.
    """

    def __init__(
        self,
        base_url: str,
        model: str = "glm-asr",
        api_key: str = "abc123",
        max_concurrent: int = 20,
        timeout: float = 300.0,
    ):
        """Initialize GLM-ASR provider.

        Args:
            base_url: vLLM API base URL (e.g., http://localhost:8000/v1)
            model: Model name (--served_model_name in vLLM)
            api_key: API key for authentication
            max_concurrent: Maximum concurrent requests
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create connection-pooled HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(
                    max_connections=self.max_concurrent,
                    max_keepalive_connections=self.max_concurrent // 2,
                ),
            )
        return self._client

    async def _get_semaphore(self) -> asyncio.Semaphore:
        """Get or create concurrency semaphore."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._semaphore

    async def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
    ) -> list[ASRSegment]:
        """Transcribe a single audio file.

        Args:
            audio_path: Path to the audio file
            language: Optional language hint (not used by GLM-ASR)

        Returns:
            List containing single ASRSegment with transcribed text
        """
        client = await self._get_client()
        headers = {"Authorization": f"Bearer {self.api_key}"}

        filename = Path(audio_path).name
        with open(audio_path, "rb") as f:
            files = {"file": (filename, f, "audio/wav")}
            data = {
                "model": self.model,
                "response_format": "text",
            }
            if language:
                data["language"] = language

            try:
                response = await client.post(
                    f"{self.base_url}/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                )
                response.raise_for_status()
                result = response.json()
            except httpx.HTTPError as exc:
                raise ProviderError("glm_asr", str(exc)) from exc

        text = result.get("text", "").strip()
        return [ASRSegment(text=text, start=0.0, end=0.0, language=language)]

    async def transcribe_segment(
        self,
        audio_path: str,
        start: float,
        end: float,
    ) -> str:
        """Transcribe a segment (audio should be pre-cut).

        Args:
            audio_path: Path to the (already cut) audio file
            start: Original start time (for metadata only)
            end: Original end time (for metadata only)

        Returns:
            Transcribed text
        """
        segments = await self.transcribe(audio_path)
        return segments[0].text if segments else ""

    async def transcribe_batch(
        self,
        audio_paths: list[str],
        language: str | None = None,
    ) -> list[str]:
        """Transcribe multiple audio files concurrently.

        Args:
            audio_paths: List of paths to audio files
            language: Optional language hint passed to the API

        Returns:
            List of transcribed texts in the same order
        """
        semaphore = await self._get_semaphore()

        async def _transcribe_one(path: str) -> str:
            async with semaphore:
                try:
                    result = await self.transcribe(path, language=language)
                    return result[0].text if result else ""
                except Exception as e:
                    # Log error but return empty string to maintain order.
                    logger.warning("asr error for %s: %s", path, e)
                    return ""

        results = await asyncio.gather(*[_transcribe_one(p) for p in audio_paths])
        return list(results)

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._semaphore = None

    async def __aenter__(self) -> "GLMASRProvider":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()
