"""Shared utilities for LLM providers."""

from __future__ import annotations

import json
import logging
from typing import Any

from subflow.providers.llm.base import LLMUsage


def parse_json_from_markdown(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM output, handling markdown code blocks."""
    raw = str(text or "")
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0]

    data = json.loads(raw.strip())
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")
    return data


def build_usage(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    *,
    total_tokens: int | None = None,
) -> LLMUsage | None:
    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = int(prompt_tokens + completion_tokens)
    return LLMUsage(
        prompt_tokens=int(prompt_tokens) if isinstance(prompt_tokens, int) else None,
        completion_tokens=int(completion_tokens) if isinstance(completion_tokens, int) else None,
        total_tokens=int(total_tokens) if isinstance(total_tokens, int) else None,
    )


def log_llm_call(
    logger: logging.Logger,
    *,
    provider: str,
    model: str,
    latency_ms: int,
    usage: LLMUsage | None,
    tool_calls: int | None = None,
) -> None:
    if tool_calls is None:
        logger.info(
            "llm call (provider=%s, model=%s, latency_ms=%s, prompt_tokens=%s, completion_tokens=%s, total_tokens=%s)",
            provider,
            model,
            int(latency_ms),
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
            getattr(usage, "total_tokens", None),
        )
        return

    logger.info(
        "llm tool call (provider=%s, model=%s, latency_ms=%s, tool_calls=%s, prompt_tokens=%s, completion_tokens=%s, total_tokens=%s)",
        provider,
        model,
        int(latency_ms),
        int(tool_calls),
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        getattr(usage, "total_tokens", None),
    )
