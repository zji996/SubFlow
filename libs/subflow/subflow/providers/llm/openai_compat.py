"""OpenAI-compatible LLM Provider implementation."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from subflow.error_codes import ErrorCode
from subflow.exceptions import ProviderError
from subflow.providers.llm.base import LLMCompletionResult, LLMProvider, LLMUsage, Message

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

_WAIT_NORMAL = wait_exponential(min=1, max=10)
_WAIT_RATE_LIMIT = wait_exponential(min=2, max=30)


class _RetryableLLMError(ProviderError):
    def __init__(
        self,
        provider: str,
        message: str,
        *,
        rate_limited: bool = False,
        error_code: ErrorCode | str | None = None,
    ) -> None:
        super().__init__(provider, message, error_code=error_code)
        self.rate_limited = rate_limited


def _wait_retry(state: RetryCallState) -> float:
    exc = state.outcome.exception() if state.outcome else None
    if isinstance(exc, _RetryableLLMError) and exc.rate_limited:
        return _WAIT_RATE_LIMIT(state)
    return _WAIT_NORMAL(state)


def _log_retry(state: RetryCallState) -> None:
    exc = state.outcome.exception() if state.outcome else None
    provider = "llm"
    model = None
    if state.args:
        provider = getattr(state.args[0], "provider", provider)
        model = getattr(state.args[0], "model", None)
    wait_s = state.next_action.sleep if state.next_action else None
    logger.warning(
        "llm retrying (provider=%s, model=%s, attempt=%s, wait_s=%s, error=%s)",
        provider,
        model,
        state.attempt_number,
        wait_s,
        exc,
    )


async def _iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield "\n".join(data_lines)


def _format_http_error(response: httpx.Response, body: bytes | None) -> str:
    status = response.status_code
    reason = response.reason_phrase
    detail = ""
    if body:
        try:
            detail = body.decode("utf-8", errors="replace").strip()
        except Exception:
            detail = repr(body)
    if detail:
        if len(detail) > 2000:
            detail = detail[:2000] + "…"
        return f"HTTP {status} {reason}: {detail}"
    return f"HTTP {status} {reason}"


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible API provider (works with OpenAI, vLLM, etc.)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4",
        base_url: str | None = None,
        provider: str = "openai",
    ) -> None:
        self.provider = provider
        resolved = str(base_url or "").strip()
        self.base_url = (resolved or DEFAULT_OPENAI_BASE_URL).rstrip("/")
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

    def _parse_usage_header(self, headers: httpx.Headers) -> LLMUsage | None:
        raw = str(headers.get("x-usage") or headers.get("x-openai-usage") or "").strip()
        if not raw:
            return None
        try:
            return self._parse_usage(json.loads(raw))
        except Exception:
            return None

    def _parse_usage(self, result: object) -> LLMUsage | None:
        if not isinstance(result, dict):
            return None
        usage = result.get("usage")
        if not isinstance(usage, dict):
            return None
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        total = usage.get("total_tokens")
        if not any(isinstance(x, int) for x in (prompt, completion, total)):
            return None
        return LLMUsage(
            prompt_tokens=int(prompt) if isinstance(prompt, int) else None,
            completion_tokens=int(completion) if isinstance(completion, int) else None,
            total_tokens=int(total) if isinstance(total, int) else None,
        )

    @retry(
        retry=retry_if_exception_type(_RetryableLLMError),
        stop=stop_after_attempt(3),
        wait=_wait_retry,
        before_sleep=_log_retry,
        reraise=True,
    )
    async def _chat_completions(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> tuple[str, LLMUsage | None, int]:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        client = await self._get_client()
        started = time.perf_counter()
        text_chunks: list[str] = []
        last_event: object | None = None
        try:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    message = _format_http_error(response, body)
                    if response.status_code == 429 or response.status_code >= 500:
                        raise _RetryableLLMError(
                            self.provider,
                            message,
                            rate_limited=response.status_code == 429,
                            error_code=ErrorCode.LLM_FAILED,
                        )
                    raise ProviderError(self.provider, message, error_code=ErrorCode.LLM_FAILED)

                usage_from_header = self._parse_usage_header(response.headers)
                async for data in _iter_sse_data(response):
                    if data.strip() == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        logger.debug("llm stream non-json data: %r", data[:200])
                        continue

                    last_event = event
                    if isinstance(event, dict) and isinstance(event.get("error"), dict):
                        error_obj = event["error"]
                        error_msg = str(error_obj.get("message") or error_obj or "unknown error")
                        raise ProviderError(
                            self.provider, error_msg, error_code=ErrorCode.LLM_FAILED
                        )

                    if not isinstance(event, dict):
                        continue
                    choices = event.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice0 = choices[0]
                    if not isinstance(choice0, dict):
                        continue
                    delta = choice0.get("delta")
                    if not isinstance(delta, dict):
                        continue
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        text_chunks.append(content)
        except httpx.TimeoutException as exc:
            logger.warning("llm request timeout: %s", exc)
            raise _RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_TIMEOUT,
            ) from exc
        except httpx.TransportError as exc:
            logger.warning("llm request failed: %s", exc)
            raise _RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_FAILED,
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage_parsed = usage_from_header or self._parse_usage(last_event)
        logger.info(
            "llm call (provider=%s, model=%s, latency_ms=%s, prompt_tokens=%s, completion_tokens=%s, total_tokens=%s)",
            self.provider,
            self.model,
            latency_ms,
            getattr(usage_parsed, "prompt_tokens", None),
            getattr(usage_parsed, "completion_tokens", None),
            getattr(usage_parsed, "total_tokens", None),
        )

        text = "".join(text_chunks)
        return text, usage_parsed, latency_ms

    async def complete(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        text, _usage, _latency_ms = await self._chat_completions(
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
        text, usage, _latency_ms = await self._chat_completions(
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
