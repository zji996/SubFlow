from __future__ import annotations

import json


def parse_id_text_array(raw_output: str, *, expected_ids: list[int]) -> dict[int, str]:
    """Parse LLM output in [{"id": x, "text": "..."}] format."""
    text = (raw_output or "").strip()

    if text.startswith("```"):
        lines = text.splitlines()
        cleaned = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(cleaned).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")

    out: dict[int, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if raw_id is None:
            continue
        try:
            seg_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if seg_id not in out:
            out[seg_id] = str(item.get("text") or "").strip()

    missing = [int(i) for i in expected_ids if int(i) not in out]
    if missing:
        raise ValueError(f"Missing translations for ids={missing}")

    return out


def parse_id_text_array_partial(raw_output: str) -> dict[int, str]:
    """Best-effort parse for [{"id": x, "text": "..."}] without enforcing expected ids."""
    text = (raw_output or "").strip()

    if text.startswith("```"):
        lines = text.splitlines()
        cleaned = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(cleaned).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")

    out: dict[int, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if raw_id is None:
            continue
        try:
            seg_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if seg_id not in out:
            out[seg_id] = str(item.get("text") or "").strip()

    return out
