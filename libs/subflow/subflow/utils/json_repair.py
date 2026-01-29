"""Utilities for repairing and safely parsing truncated JSON."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def repair_truncated_json(text: str) -> str:
    """Attempt to repair a truncated JSON string.

    Handles common truncation issues:
    - Unterminated strings (missing closing quote)
    - Unterminated objects (missing closing brace)
    - Unterminated arrays (missing closing bracket)

    Args:
        text: The potentially truncated JSON string

    Returns:
        The repaired JSON string (best effort)
    """
    if not text or not text.strip():
        return "{}"

    text = text.strip()

    # Track nesting
    in_string = False
    escape_next = False
    brace_count = 0
    bracket_count = 0

    for char in text:
        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
        elif not in_string:
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
            elif char == "[":
                bracket_count += 1
            elif char == "]":
                bracket_count -= 1

    result = text

    # If we're still in a string, close it
    if in_string:
        result += '"'

    # Close any open brackets
    while bracket_count > 0:
        result += "]"
        bracket_count -= 1

    # Close any open braces
    while brace_count > 0:
        result += "}"
        brace_count -= 1

    return result


def parse_json_safe(raw: str) -> dict | list | None:
    """Safely parse JSON with repair attempt on failure.

    Args:
        raw: Raw JSON string (possibly truncated)

    Returns:
        Parsed JSON (dict or list) or None if unparseable
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to repair and parse
    try:
        repaired = repair_truncated_json(text)
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Try extracting just the object/array portion
    # Sometimes there's extra text before/after
    match = re.search(r"(\{[^{}]*\}|\[[^\[\]]*\])", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    logger.debug("Failed to parse JSON even after repair: %s...", text[:100])
    return None


def parse_tool_arguments_safe(raw: str) -> dict | None:
    """Safely parse tool call arguments JSON.

    This is specifically designed for parsing tool_call arguments
    which should always be a dict.

    Args:
        raw: Raw arguments JSON string

    Returns:
        Parsed dict or None if unparseable
    """
    result = parse_json_safe(raw)
    if isinstance(result, dict):
        return result
    return None
