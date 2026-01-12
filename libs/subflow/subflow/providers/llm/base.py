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
