"""LLM Provider implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from subflow.providers.llm.base import LLMCompletionResult, LLMProvider, LLMUsage, Message

if TYPE_CHECKING:
    from subflow.providers.llm.anthropic import AnthropicProvider
    from subflow.providers.llm.claude import ClaudeProvider

__all__ = ["AnthropicProvider", "ClaudeProvider", "LLMCompletionResult", "LLMProvider", "LLMUsage", "Message"]


def __getattr__(name: str) -> Any:
    if name == "AnthropicProvider":
        from subflow.providers.llm.anthropic import AnthropicProvider

        return AnthropicProvider
    if name == "ClaudeProvider":
        from subflow.providers.llm.claude import ClaudeProvider

        return ClaudeProvider
    raise AttributeError(name)
