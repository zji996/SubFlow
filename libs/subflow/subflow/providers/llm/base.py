"""LLM Provider base class."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class Message:
    """A chat message."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class LLMCompletionResult:
    text: str
    usage: LLMUsage | None = None


@dataclass(frozen=True)
class ToolDefinition:
    """Tool/Function definition (OpenAI-style JSON Schema parameters)."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """A single tool/function call returned by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolCallResult:
    """Tool use result (one request may contain multiple tool calls)."""

    tool_calls: list[ToolCall]
    usage: LLMUsage | None = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a completion.

        Args:
            messages: List of chat messages.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            Generated text.
        """
        ...

    async def complete_with_usage(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMCompletionResult:
        text = await self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        return LLMCompletionResult(text=text, usage=None)

    async def complete_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        parallel_tool_calls: bool = True,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ToolCallResult:
        raise NotImplementedError("Tool use is not supported by this LLM provider")

    @abstractmethod
    async def complete_json(
        self,
        messages: list[Message],
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Generate a structured JSON response.

        Args:
            messages: List of chat messages.
            temperature: Sampling temperature.

        Returns:
            Parsed JSON object.
        """
        ...

    async def close(self) -> None:
        """Close any underlying resources (optional)."""
        return None
