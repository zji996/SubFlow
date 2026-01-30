"""OpenAI-compatible LLM Provider implementation."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
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
from subflow.providers.llm._utils import log_llm_call, parse_json_from_markdown

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


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


def _looks_like_tool_use_unsupported(message: str) -> bool:
    msg = str(message or "").lower()
    return any(
        token in msg
        for token in (
            "unknown parameter: tools",
            "unknown parameter: tool_choice",
            "unknown parameter: parallel_tool_calls",
            'unrecognized field "tools"',
            'unrecognized field "tool_choice"',
            'unrecognized field "parallel_tool_calls"',
            "does not support tools",
            "tool calls are not supported",
        )
    )


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
        retry=retry_if_exception_type(RetryableLLMError),
        stop=stop_after_attempt(3),
        wait=wait_retry,
        before_sleep=log_retry(logger),
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
                        raise RetryableLLMError(
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
            raise RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_TIMEOUT,
            ) from exc
        except httpx.TransportError as exc:
            logger.warning("llm request failed: %s", exc)
            raise RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_FAILED,
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage_parsed = usage_from_header or self._parse_usage(last_event)
        log_llm_call(
            logger,
            provider=self.provider,
            model=self.model,
            latency_ms=latency_ms,
            usage=usage_parsed,
        )

        text = "".join(text_chunks)
        return text, usage_parsed, latency_ms

    @retry(
        retry=retry_if_exception_type(RetryableLLMError),
        stop=stop_after_attempt(3),
        wait=wait_retry,
        before_sleep=log_retry(logger),
        reraise=True,
    )
    async def _chat_completions_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        parallel_tool_calls: bool,
        temperature: float,
        max_tokens: int | None,
    ) -> tuple[list[ToolCall], LLMUsage | None, int]:
        strict = self.provider == "openai" and self.base_url == DEFAULT_OPENAI_BASE_URL.rstrip("/")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": float(temperature),
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        **({"strict": True} if strict else {}),
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ],
            "parallel_tool_calls": bool(parallel_tool_calls),
            "tool_choice": "required",
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)

        client = await self._get_client()
        started = time.perf_counter()
        last_event: object | None = None
        tool_call_buffers: dict[int, dict[str, Any]] = {}

        async def _run_request(
            payload_override: dict[str, Any],
        ) -> tuple[LLMUsage | None, object | None]:
            nonlocal last_event
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload_override,
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    message = _format_http_error(response, body)
                    if response.status_code == 400 and _looks_like_tool_use_unsupported(message):
                        raise NotImplementedError(message)
                    if response.status_code == 429 or response.status_code >= 500:
                        raise RetryableLLMError(
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
                    tool_calls = delta.get("tool_calls")
                    if not isinstance(tool_calls, list) or not tool_calls:
                        continue
                    for tc in tool_calls:
                        if not isinstance(tc, dict):
                            continue
                        index = tc.get("index")
                        if not isinstance(index, int):
                            continue
                        buf = tool_call_buffers.setdefault(index, {"arguments": ""})
                        if isinstance(tc.get("id"), str):
                            buf["id"] = tc["id"]
                        func = tc.get("function")
                        if isinstance(func, dict):
                            if isinstance(func.get("name"), str) and func["name"]:
                                buf["name"] = func["name"]
                            if isinstance(func.get("arguments"), str) and func["arguments"]:
                                buf["arguments"] = (
                                    str(buf.get("arguments") or "") + func["arguments"]
                                )

                return usage_from_header, last_event

        try:
            try:
                usage_from_header, last_event = await _run_request(payload)
            except ProviderError as exc:
                # Some proxies reject "strict" and/or "parallel_tool_calls". Retry once without them.
                msg = str(exc).lower()
                if "unknown parameter: strict" in msg or 'unrecognized field "strict"' in msg:
                    payload2 = json.loads(json.dumps(payload))
                    for item in payload2.get("tools", []):
                        func = item.get("function") if isinstance(item, dict) else None
                        if isinstance(func, dict):
                            func.pop("strict", None)
                    usage_from_header, last_event = await _run_request(payload2)
                elif (
                    "unknown parameter: parallel_tool_calls" in msg
                    or 'unrecognized field "parallel_tool_calls"' in msg
                ):
                    payload2 = dict(payload)
                    payload2.pop("parallel_tool_calls", None)
                    usage_from_header, last_event = await _run_request(payload2)
                else:
                    raise
        except httpx.TimeoutException as exc:
            logger.warning("llm request timeout: %s", exc)
            raise RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_TIMEOUT,
            ) from exc
        except httpx.TransportError as exc:
            logger.warning("llm request failed: %s", exc)
            raise RetryableLLMError(
                self.provider,
                str(exc),
                error_code=ErrorCode.LLM_FAILED,
            ) from exc

        usage_parsed = usage_from_header or self._parse_usage(last_event)
        latency_ms = int((time.perf_counter() - started) * 1000)

        parsed_calls: list[ToolCall] = []
        from subflow.utils.json_repair import parse_tool_arguments_safe

        for index in sorted(tool_call_buffers):
            buf = tool_call_buffers[index]
            name = str(buf.get("name") or "").strip()
            if not name:
                continue
            call_id = str(buf.get("id") or f"call_{index}")
            raw_args = str(buf.get("arguments") or "").strip()

            # Use safe parser that handles truncated JSON
            args = parse_tool_arguments_safe(raw_args)
            if args is None:
                logger.warning(
                    "Skipping tool_call with unparseable arguments (tool=%s, id=%s, args=%s...)",
                    name,
                    call_id,
                    raw_args[:80] if raw_args else "",
                )
                continue
            parsed_calls.append(ToolCall(id=call_id, name=name, arguments=args))

        log_llm_call(
            logger,
            provider=self.provider,
            model=self.model,
            latency_ms=latency_ms,
            usage=usage_parsed,
            tool_calls=len(parsed_calls),
        )

        return parsed_calls, usage_parsed, latency_ms

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
            return parse_json_from_markdown(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse JSON response: {exc}") from exc

    async def complete_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        parallel_tool_calls: bool = True,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ToolCallResult:
        tool_calls, usage, _latency_ms = await self._chat_completions_with_tools(
            messages,
            tools,
            parallel_tool_calls=parallel_tool_calls,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return ToolCallResult(tool_calls=tool_calls, usage=usage)

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
