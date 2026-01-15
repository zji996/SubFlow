"""LLM JSON parsing utilities with Markdown code block support and retry logic."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, cast

from subflow.providers.llm import LLMProvider, LLMUsage, Message
from subflow.utils.tokenizer import count_tokens


_THINK_BLOCK_RE = re.compile(r"^\s*<think>[\s\S]*?</think>\s*", re.IGNORECASE)
_THINK_TAG_RE = re.compile(r"</?think>\s*", re.IGNORECASE)

JSONData = dict[str, Any] | list[Any]


def parse_llm_json(text: str) -> JSONData:
    """Parse JSON from LLM output, supporting Markdown code blocks.

    Handles:
    - Plain JSON
    - ```json ... ``` code blocks
    - ``` ... ``` code blocks

    Args:
        text: Raw LLM output text

    Returns:
        Parsed JSON as dict or list

    Raises:
        json.JSONDecodeError: If JSON parsing fails
    """
    text = (text or "").strip()
    # Some providers/models may include explicit reasoning blocks.
    text = _THINK_BLOCK_RE.sub("", text).strip()
    text = _THINK_TAG_RE.sub("", text).strip()

    # Try to extract Markdown code blocks
    patterns = [
        r"```json\s*([\s\S]*?)\s*```",  # ```json ... ```
        r"```\s*([\s\S]*?)\s*```",  # ``` ... ```
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            text = match.group(1).strip()
            break

    # Parse JSON (best-effort extraction when extra text is present)
    first_error: json.JSONDecodeError | None = None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return cast(dict[str, Any], data)
        if isinstance(data, list):
            return data
        raise json.JSONDecodeError("Expected a JSON object/array", text, 0)
    except json.JSONDecodeError as exc:
        first_error = exc

    # Heuristic: extract the first JSON object/array payload from the text.
    starts: list[tuple[int, str]] = []
    for ch in ("{", "["):
        idx = text.find(ch)
        if idx != -1:
            starts.append((idx, ch))
    if not starts:
        assert first_error is not None
        raise first_error

    start_idx, start_ch = min(starts, key=lambda x: x[0])
    end_ch = "}" if start_ch == "{" else "]"
    end_idx = text.rfind(end_ch)
    if end_idx <= start_idx:
        assert first_error is not None
        raise first_error

    candidate = text[start_idx : end_idx + 1].strip()
    data2 = json.loads(candidate)
    if isinstance(data2, dict):
        return cast(dict[str, Any], data2)
    if isinstance(data2, list):
        return data2
    raise json.JSONDecodeError("Expected a JSON object/array", candidate, 0)


@dataclass
class JSONRetryResult:
    """Result of JSON parsing with retry."""

    data: JSONData | None
    success: bool
    attempts: int
    last_error: str | None = None


class LLMJSONHelper:
    """Helper for LLM JSON parsing with retry logic."""

    MAX_RETRIES = 3

    def __init__(self, llm: LLMProvider, max_retries: int = 3) -> None:
        """Initialize helper.

        Args:
            llm: LLM provider instance
            max_retries: Maximum retry attempts (default 3)
        """
        self.llm = llm
        self.max_retries = max_retries

    @staticmethod
    def _estimate_usage(messages: list[Message], response_text: str) -> LLMUsage:
        prompt_text = "\n".join(f"{m.role}: {m.content}" for m in messages)
        prompt_tokens = count_tokens(prompt_text)
        completion_tokens = count_tokens(response_text or "")
        return LLMUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    async def complete_json_with_retry(
        self,
        messages: list[Message],
        temperature: float = 0.3,
    ) -> JSONData:
        """Complete LLM request and parse JSON with retry.

        Args:
            messages: Conversation messages
            temperature: LLM temperature

        Returns:
            Parsed JSON data

        Raises:
            ValueError: If JSON parsing fails after all retries
        """
        current_messages = list(messages)
        last_error: Exception | None = None
        last_response: str = ""

        for attempt in range(self.max_retries):
            try:
                completion = await self.llm.complete_with_usage(
                    current_messages, temperature=temperature
                )
                last_response = completion.text
                return parse_llm_json(completion.text)
            except json.JSONDecodeError as e:
                last_error = e

                if attempt < self.max_retries - 1:
                    # Add error feedback for retry
                    current_messages = current_messages + [
                        Message(role="assistant", content=last_response),
                        Message(
                            role="user",
                            content=(
                                f"JSON 解析失败：{e.msg}（位置 {e.pos}）。\n"
                                "请重新输出有效的 JSON。你可以使用 ```json ... ``` 格式。"
                            ),
                        ),
                    ]

        raise ValueError(
            f"JSON 解析失败，已重试 {self.max_retries} 次。\n"
            f"最后错误：{last_error}\n"
            f"最后响应：{last_response[:500]}..."
        )

    async def complete_json(
        self,
        messages: list[Message],
        temperature: float = 0.3,
    ) -> JSONData:
        """Alias for complete_json_with_retry."""
        return await self.complete_json_with_retry(messages, temperature)

    async def complete_json_with_usage(
        self,
        messages: list[Message],
        temperature: float = 0.3,
    ) -> tuple[JSONData, LLMUsage]:
        current_messages = list(messages)
        last_error: Exception | None = None
        last_response: str = ""
        last_usage: LLMUsage | None = None

        for attempt in range(self.max_retries):
            try:
                completion = await self.llm.complete_with_usage(
                    current_messages, temperature=temperature
                )
                last_response = completion.text
                last_usage = completion.usage or self._estimate_usage(
                    current_messages, completion.text
                )
                return parse_llm_json(completion.text), last_usage
            except json.JSONDecodeError as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    current_messages = current_messages + [
                        Message(role="assistant", content=last_response),
                        Message(
                            role="user",
                            content=(
                                f"JSON 解析失败：{exc.msg}（位置 {exc.pos}）。\n"
                                "请重新输出有效的 JSON。你可以使用 ```json ... ``` 格式。"
                            ),
                        ),
                    ]

        raise ValueError(
            f"JSON 解析失败，已重试 {self.max_retries} 次。\n"
            f"最后错误：{last_error}\n"
            f"最后响应：{last_response[:500]}..."
        )
