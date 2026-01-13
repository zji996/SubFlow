"""Anthropic LLM Provider implementation (Messages API)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from subflow.error_codes import ErrorCode
from subflow.exceptions import ProviderError
from subflow.providers.llm.base import LLMCompletionResult, LLMProvider, LLMUsage, Message

logger = logging.getLogger(__name__)

DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 1024


def _coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _split_system_messages(messages: list[Message]) -> tuple[str | None, list[Message]]:
    system_chunks: list[str] = []
    non_system: list[Message] = []
    for m in messages:
        role = str(m.role or "").strip().lower()
        if role == "system":
            if m.content:
                system_chunks.append(str(m.content))
            continue
        non_system.append(m)
    system = "\n\n".join(system_chunks).strip() if system_chunks else ""
    return (system or None), non_system


def _to_anthropic_messages(messages: list[Message]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages:
        role = str(m.role or "").strip().lower()
        if role not in {"user", "assistant"}:
            role = "user"
        out.append({"role": role, "content": str(m.content or "")})
    return out


def _parse_text(result: object) -> str:
    if not isinstance(result, dict):
        return ""
    content = result.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() != "text":
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            chunks.append(text)
    return "".join(chunks).strip()


def _parse_usage(result: object) -> LLMUsage | None:
    if not isinstance(result, dict):
        return None
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = _coerce_int(usage.get("input_tokens"))
    completion = _coerce_int(usage.get("output_tokens"))
    if prompt is None and completion is None:
        return None
    total = (prompt or 0) + (completion or 0) if (prompt is not None and completion is not None) else None
    return LLMUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


class AnthropicProvider(LLMProvider):
    """Anthropic provider via Messages API."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        base_url: str | None = None,
    ) -> None:
        self.provider = "anthropic"
        self.api_key = str(api_key or "").strip()
        if not self.api_key:
            raise ValueError("AnthropicProvider requires api_key")
        self.model = str(model or "").strip() or "claude-sonnet-4-20250514"
        resolved = str(base_url or "").strip()
        self.base_url = (resolved or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
    )
    async def _messages(
        self,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int | None,
    ) -> tuple[str, LLMUsage | None, int]:
        system, non_system = _split_system_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _to_anthropic_messages(non_system),
            "temperature": float(temperature),
            "max_tokens": int(max_tokens) if max_tokens is not None else int(DEFAULT_MAX_TOKENS),
        }
        if system:
            payload["system"] = system

        client = await self._get_client()
        started = time.perf_counter()
        try:
            response = await client.post(
                self._endpoint(),
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
        except httpx.TimeoutException as exc:
            logger.warning("llm request timeout: %s", exc)
            raise ProviderError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("llm request failed: %s", exc)
            raise ProviderError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_FAILED,
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage_parsed = _parse_usage(result)
        logger.info(
            "llm call (provider=%s, model=%s, latency_ms=%s, prompt_tokens=%s, completion_tokens=%s, total_tokens=%s)",
            self.provider,
            self.model,
            latency_ms,
            getattr(usage_parsed, "prompt_tokens", None),
            getattr(usage_parsed, "completion_tokens", None),
            getattr(usage_parsed, "total_tokens", None),
        )

        return _parse_text(result), usage_parsed, latency_ms

    async def complete(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        text, _usage, _latency_ms = await self._messages(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return text

    async def complete_with_usage(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMCompletionResult:
        text, usage, _latency_ms = await self._messages(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LLMCompletionResult(text=text, usage=usage)

    async def complete_json(
        self,
        messages: list[Message],
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        json_messages = list(messages)
        if json_messages and str(json_messages[0].role or "").strip().lower() == "system":
            json_messages[0] = Message(
                role="system",
                content=str(json_messages[0].content or "") + "\n\nRespond with valid JSON only.",
            )
        else:
            json_messages.insert(0, Message(role="system", content="Respond with valid JSON only."))

        text = await self.complete(json_messages, temperature=temperature)
        try:
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            data = json.loads(text.strip())
            if not isinstance(data, dict):
                raise ValueError(f"Expected JSON object, got {type(data).__name__}")
            return data
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse JSON response: {exc}") from exc

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "AnthropicProvider":
        await self._get_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        await self.close()
