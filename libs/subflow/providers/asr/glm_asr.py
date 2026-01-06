"""GLM-ASR Provider implementation."""

import httpx

from libs.subflow.providers.asr.base import ASRProvider, ASRSegment


class GLMASRProvider(ASRProvider):
    """GLM-ASR API provider (OpenAI-compatible interface)."""

    def __init__(
        self,
        base_url: str,
        model: str = "glm-asr-nano-2512",
        api_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    async def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
    ) -> list[ASRSegment]:
        """Transcribe audio using GLM-ASR API."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient() as client:
            with open(audio_path, "rb") as f:
                files = {"file": (audio_path, f, "audio/wav")}
                data = {"model": self.model}
                if language:
                    data["language"] = language

                response = await client.post(
                    f"{self.base_url}/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=300.0,
                )
                response.raise_for_status()
                result = response.json()

        # Parse response - GLM-ASR returns text directly
        text = result.get("text", "")
        return [ASRSegment(text=text, start=0.0, end=0.0, language=language)]

    async def transcribe_segment(
        self,
        audio_path: str,
        start: float,
        end: float,
    ) -> str:
        """Transcribe a segment (requires pre-cut audio)."""
        segments = await self.transcribe(audio_path)
        return segments[0].text if segments else ""
