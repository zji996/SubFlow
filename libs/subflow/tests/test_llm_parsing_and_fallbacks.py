from __future__ import annotations

import pytest

from subflow.models.segment import ASRSegment
from subflow.stages.llm_asr_correction import LLMASRCorrectionStage
from subflow.stages.llm_passes import SemanticChunkingPass, _compact_global_context
from subflow.utils.llm_json_parser import parse_id_text_array


@pytest.mark.asyncio
async def test_llm_asr_correction_fallback_keeps_all_segments(settings) -> None:
    stage = LLMASRCorrectionStage.__new__(LLMASRCorrectionStage)
    stage.settings = settings
    stage.profile = "fast"
    stage.api_key = ""

    ctx = {"asr_segments": [ASRSegment(id=0, start=0.0, end=1.0, text="hi", language="en")]}
    out = await stage.execute(ctx)
    assert "asr_corrected_segments" in out
    assert out["asr_corrected_segments"][0].text == "hi"
    assert out["asr_segments_index"][0].text == "hi"


def test_compact_global_context_defaults() -> None:
    ctx = _compact_global_context({"topic": "", "glossary": {"a": "b"}})
    assert ctx["topic"] == "unknown"
    assert ctx["glossary"] == {"a": "b"}


def test_parse_id_text_array_parses_expected_ids() -> None:
    out = parse_id_text_array(
        '```json\n[{"id": 0, "text": "hi"}, {"id": 1, "text": "there"}]\n```',
        expected_ids=[0, 1],
    )
    assert out == {0: "hi", 1: "there"}


def test_parse_id_text_array_raises_on_missing_ids() -> None:
    with pytest.raises(ValueError):
        parse_id_text_array('[{"id": 0, "text": "hi"}]', expected_ids=[0, 1])


def test_semantic_chunking_batches_extend_to_sentence_endings() -> None:
    segments = [
        ASRSegment(id=0, start=0.0, end=1.0, text="A"),
        ASRSegment(id=1, start=1.0, end=2.0, text="B"),
        ASRSegment(id=2, start=2.0, end=3.0, text="C."),
        ASRSegment(id=3, start=3.0, end=4.0, text="D?"),
    ]
    batches = SemanticChunkingPass._build_translation_batches(
        segments,
        get_text=lambda s: s.text,
        max_segments_per_batch=2,
        sentence_endings=".",
    )
    assert [[s.id for s in batch] for batch in batches] == [[0, 1, 2], [3]]
