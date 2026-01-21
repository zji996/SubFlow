from __future__ import annotations

from subflow.utils.llm_json_parser import parse_id_text_array


def test_parse_id_text_array_strips_markdown_fences() -> None:
    """Verify that parse_id_text_array handles markdown code fences."""
    raw = '```json\n[{"id": 0, "text": "hi"}]\n```'
    out = parse_id_text_array(raw, expected_ids=[0])
    assert out == {0: "hi"}


def test_parse_id_text_array_strips_whitespace() -> None:
    """Verify that text values are stripped."""
    raw = '[{"id": 0, "text": "  hi  "}]'
    out = parse_id_text_array(raw, expected_ids=[0])
    assert out == {0: "hi"}
