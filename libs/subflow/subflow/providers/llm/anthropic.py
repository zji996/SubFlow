"""Anthropic LLM Provider implementation using official SDK."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Literal

import anthropic
from anthropic.types import MessageParam
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
)

from subflow.error_codes import ErrorCode
from subflow.exceptions import ProviderError
from subflow.providers.llm.base import (
    LLMCompletionResult,
    LLMProvider,
    LLMUsage,
    Message,
    ToolCall,
    ToolCallResult,
    ToolDefinition,
)
from subflow.providers.llm._retry import RetryableLLMError, log_retry, wait_retry
from subflow.providers.llm._utils import build_usage, log_llm_call, parse_json_from_markdown

logger = logging.getLogger(__name__)

DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_MAX_TOKENS = 4096


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


def _to_anthropic_messages(messages: list[Message]) -> list[MessageParam]:
    out: list[MessageParam] = []
    for m in messages:
        role = str(m.role or "").strip().lower()
        typed_role: Literal["user", "assistant"]
        if role == "assistant":
            typed_role = "assistant"
        else:
            typed_role = "user"
        out.append({"role": typed_role, "content": str(m.content or "")})
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
        retry=retry_if_exception_type(RetryableLLMError),
        stop=stop_after_attempt(3),
        wait=wait_retry,
        before_sleep=log_retry(logger),
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
            stream_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": _to_anthropic_messages(non_system),
                "temperature": float(temperature),
                "max_tokens": int(max_tokens) if max_tokens is not None else DEFAULT_MAX_TOKENS,
            }
            if system:
                stream_kwargs["system"] = system

            async with self._client.messages.stream(**stream_kwargs) as stream:
                async for text in stream.text_stream:
                    text_chunks.append(text)

                # Get final message for usage info
                final_message = await stream.get_final_message()
                if final_message and final_message.usage:
                    usage_prompt = final_message.usage.input_tokens
                    usage_completion = final_message.usage.output_tokens

        except anthropic.RateLimitError as exc:
            logger.warning("llm rate limited: %s", exc)
            raise RetryableLLMError(
                self.provider,
                str(exc),
                rate_limited=True,
                error_code=ErrorCode.LLM_FAILED,
            ) from exc
        except anthropic.APIStatusError as exc:
            # 5xx errors are retryable
            if exc.status_code >= 500:
                logger.warning("llm server error: %s", exc)
                raise RetryableLLMError(
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
            raise RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_TIMEOUT,
            ) from exc
        except anthropic.APITimeoutError as exc:
            logger.warning("llm timeout: %s", exc)
            raise RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_TIMEOUT,
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage_parsed = build_usage(usage_prompt, usage_completion)
        log_llm_call(
            logger,
            provider=self.provider,
            model=self.model,
            latency_ms=latency_ms,
            usage=usage_parsed,
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
            return parse_json_from_markdown(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse JSON response: {exc}") from exc

    @retry(
        retry=retry_if_exception_type(RetryableLLMError),
        stop=stop_after_attempt(3),
        wait=wait_retry,
        before_sleep=log_retry(logger),
        reraise=True,
    )
    async def _messages_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        parallel_tool_calls: bool,
        temperature: float,
        max_tokens: int | None,
    ) -> tuple[list[ToolCall], LLMUsage | None, int]:
        system, non_system = _split_system_messages(messages)
        started = time.perf_counter()
        try:
            request: dict[str, Any] = {
                "model": self.model,
                "messages": _to_anthropic_messages(non_system),
                "temperature": float(temperature),
                "max_tokens": int(max_tokens) if max_tokens is not None else DEFAULT_MAX_TOKENS,
            }
            if system:
                request["system"] = system
            if tools:
                request["tools"] = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": t.parameters,
                    }
                    for t in tools
                ]
                request["tool_choice"] = (
                    {"type": "any"}
                    if parallel_tool_calls
                    else {"type": "tool", "name": tools[0].name}
                )
            response = await self._client.messages.create(**request)
        except anthropic.RateLimitError as exc:
            logger.warning("llm rate limited: %s", exc)
            raise RetryableLLMError(
                self.provider,
                str(exc),
                rate_limited=True,
                error_code=ErrorCode.LLM_FAILED,
            ) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code == 400 and "tools" in str(exc).lower():
                raise NotImplementedError(str(exc)) from exc
            if exc.status_code >= 500:
                logger.warning("llm server error: %s", exc)
                raise RetryableLLMError(
                    self.provider,
                    str(exc),
                    error_code=ErrorCode.LLM_FAILED,
                ) from exc
            logger.warning("llm request failed: %s", exc)
            raise ProviderError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_FAILED,
            ) from exc
        except anthropic.APIConnectionError as exc:
            logger.warning("llm connection error: %s", exc)
            raise RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_TIMEOUT,
            ) from exc
        except anthropic.APITimeoutError as exc:
            logger.warning("llm timeout: %s", exc)
            raise RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_TIMEOUT,
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "input_tokens", None)
        completion_tokens = getattr(usage, "output_tokens", None)
        usage_parsed = build_usage(
            int(prompt_tokens) if isinstance(prompt_tokens, int) else None,
            int(completion_tokens) if isinstance(completion_tokens, int) else None,
        )

        tool_calls: list[ToolCall] = []
        from subflow.utils.json_repair import parse_tool_arguments_safe

        for block in list(getattr(response, "content", None) or []):
            block_type = getattr(block, "type", None)
            if block_type != "tool_use":
                continue
            name = str(getattr(block, "name", "") or "").strip()
            call_id = str(getattr(block, "id", "") or "").strip() or "tool_use"
            args = getattr(block, "input", None)
            if isinstance(args, str):
                parsed = parse_tool_arguments_safe(args)
                if parsed is None:
                    logger.warning(
                        "Skipping tool_call with unparseable arguments (tool=%s, id=%s, args=%s...)",
                        name,
                        call_id,
                        args[:80] if args else "",
                    )
                    continue
                args = parsed
            if not isinstance(args, dict):
                continue
            tool_calls.append(ToolCall(id=call_id, name=name, arguments=args))

        log_llm_call(
            logger,
            provider=self.provider,
            model=self.model,
            latency_ms=latency_ms,
            usage=usage_parsed,
            tool_calls=len(tool_calls),
        )
        return tool_calls, usage_parsed, latency_ms

    async def complete_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        parallel_tool_calls: bool = True,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ToolCallResult:
        tool_calls, usage, _latency_ms = await self._messages_with_tools(
            messages,
            tools,
            parallel_tool_calls=parallel_tool_calls,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return ToolCallResult(tool_calls=tool_calls, usage=usage)

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
