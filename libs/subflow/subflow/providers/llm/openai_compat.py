"""OpenAI-compatible LLM Provider implementation."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from subflow.error_codes import ErrorCode
from subflow.exceptions import ProviderError
from subflow.providers.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible API provider (works with OpenAI, vLLM, etc.)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "gpt-4",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
    )
    async def complete(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a completion using OpenAI-compatible API."""
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        client = await self._get_client()
        started = time.perf_counter()
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
        except httpx.TimeoutException as exc:
            logger.warning("llm request timeout: %s", exc)
            raise ProviderError(
                "openai_compat",
                str(exc),
                error_code=ErrorCode.LLM_TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("llm request failed: %s", exc)
            raise ProviderError(
                "openai_compat",
                str(exc),
                error_code=ErrorCode.LLM_FAILED,
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = result.get("usage") if isinstance(result, dict) else None
        tokens_used: int | None = None
        if isinstance(usage, dict):
            raw = usage.get("total_tokens")
            if isinstance(raw, int):
                tokens_used = raw
        logger.info(
            "llm call (provider=%s, model=%s, latency_ms=%s, tokens_used=%s)",
            "openai_compat",
            self.model,
            latency_ms,
            tokens_used,
        )

        return str(result["choices"][0]["message"]["content"])

    async def complete_json(
        self,
        messages: list[Message],
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Generate a structured JSON response."""
        # Add JSON instruction to system prompt
        json_messages = list(messages)
        if json_messages and json_messages[0].role == "system":
            json_messages[0] = Message(
                role="system",
                content=json_messages[0].content + "\n\nRespond with valid JSON only.",
            )

        text = await self.complete(json_messages, temperature=temperature)

        # Parse JSON from response
        try:
            # Handle markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            data = json.loads(text.strip())
            if not isinstance(data, dict):
                raise ValueError(f"Expected JSON object, got {type(data).__name__}")
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {e}") from e

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "OpenAICompatProvider":
        await self._get_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        await self.close()
