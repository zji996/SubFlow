from __future__ import annotations

from subflow.utils.llm_json import parse_llm_json


def test_parse_llm_json_handles_think_prefix() -> None:
    raw = "<think>reasoning...</think>\n{\"a\": 1, \"b\": [2, 3]}\n"
    out = parse_llm_json(raw)
    assert out == {"a": 1, "b": [2, 3]}


def test_parse_llm_json_extracts_json_from_mixed_text() -> None:
    raw = "some text before\\n[1, 2, 3]\\nsome text after"
    out = parse_llm_json(raw)
    assert out == [1, 2, 3]
