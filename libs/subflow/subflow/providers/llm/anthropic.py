"""Anthropic LLM Provider implementation using official SDK."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import anthropic
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from subflow.error_codes import ErrorCode
from subflow.exceptions import ProviderError
from subflow.providers.llm.base import LLMCompletionResult, LLMProvider, LLMUsage, Message

logger = logging.getLogger(__name__)

DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_MAX_TOKENS = 4096

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


class AnthropicProvider(LLMProvider):
    """Anthropic provider using official SDK with streaming support."""

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
        
        # Handle base_url - SDK expects it without /v1 suffix
        resolved = str(base_url or "").strip().rstrip("/")
        if resolved.endswith("/v1"):
            resolved = resolved[:-3]
        self.base_url = resolved or None
        
        # Create async client
        self._client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=120.0,
        )

    @retry(
        retry=retry_if_exception_type(_RetryableLLMError),
        stop=stop_after_attempt(3),
        wait=_wait_retry,
        before_sleep=_log_retry,
        reraise=True,
    )
    async def _messages(
        self,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int | None,
    ) -> tuple[str, LLMUsage | None, int]:
        system, non_system = _split_system_messages(messages)
        
        started = time.perf_counter()
        text_chunks: list[str] = []
        usage_prompt: int | None = None
        usage_completion: int | None = None

        try:
            # Use streaming mode for better proxy compatibility
            async with self._client.messages.stream(
                model=self.model,
                messages=_to_anthropic_messages(non_system),
                system=system or anthropic.NOT_GIVEN,
                temperature=float(temperature),
                max_tokens=int(max_tokens) if max_tokens is not None else DEFAULT_MAX_TOKENS,
            ) as stream:
                async for text in stream.text_stream:
                    text_chunks.append(text)
                
                # Get final message for usage info
                final_message = await stream.get_final_message()
                if final_message and final_message.usage:
                    usage_prompt = final_message.usage.input_tokens
                    usage_completion = final_message.usage.output_tokens

        except anthropic.RateLimitError as exc:
            logger.warning("llm rate limited: %s", exc)
            raise _RetryableLLMError(
                self.provider,
                str(exc),
                rate_limited=True,
                error_code=ErrorCode.LLM_FAILED,
            ) from exc
        except anthropic.APIStatusError as exc:
            # 5xx errors are retryable
            if exc.status_code >= 500:
                logger.warning("llm server error: %s", exc)
                raise _RetryableLLMError(
                    self.provider,
                    str(exc),
                    error_code=ErrorCode.LLM_FAILED,
                ) from exc
            # 4xx errors (except rate limit) are not retryable
            logger.warning("llm request failed: %s", exc)
            raise ProviderError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_FAILED,
            ) from exc
        except anthropic.APIConnectionError as exc:
            logger.warning("llm connection error: %s", exc)
            raise _RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_TIMEOUT,
            ) from exc
        except anthropic.APITimeoutError as exc:
            logger.warning("llm timeout: %s", exc)
            raise _RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_TIMEOUT,
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage_parsed: LLMUsage | None = None
        if usage_prompt is not None or usage_completion is not None:
            total = (
                (usage_prompt or 0) + (usage_completion or 0)
                if usage_prompt is not None and usage_completion is not None
                else None
            )
            usage_parsed = LLMUsage(
                prompt_tokens=usage_prompt,
                completion_tokens=usage_completion,
                total_tokens=total,
            )
        logger.info(
            "llm call (provider=%s, model=%s, latency_ms=%s, prompt_tokens=%s, completion_tokens=%s, total_tokens=%s)",
            self.provider,
            self.model,
            latency_ms,
            getattr(usage_parsed, "prompt_tokens", None),
            getattr(usage_parsed, "completion_tokens", None),
            getattr(usage_parsed, "total_tokens", None),
        )

        return "".join(text_chunks), usage_parsed, latency_ms

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
            await self._client.close()

    async def __aenter__(self) -> "AnthropicProvider":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        await self.close()
