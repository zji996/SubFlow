"""Backward-compatible import path for the Anthropic provider."""

from __future__ import annotations

from subflow.providers.llm.anthropic import AnthropicProvider as ClaudeProvider

__all__ = ["ClaudeProvider"]
