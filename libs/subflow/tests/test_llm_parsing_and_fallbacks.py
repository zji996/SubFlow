from __future__ import annotations

import pytest

from subflow.models.segment import ASRSegment
from subflow.stages.llm_asr_correction import LLMASRCorrectionStage
from subflow.stages.llm_passes import SemanticChunkingPass, _compact_global_context


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


def test_semantic_chunking_clean_translation_strips_code_fences_and_quotes() -> None:
    stage = SemanticChunkingPass.__new__(SemanticChunkingPass)
    assert stage._clean_translation("```text\nhi\n```") == "hi"
    assert stage._clean_translation('"hi"') == "hi"
    assert stage._clean_translation(" hi ") == "hi"


def test_semantic_chunking_parse_batch_translation_parses_expected_ids() -> None:
    out = SemanticChunkingPass._parse_batch_translation(
        '```text\n[0]: hi\n[1]: "there"\n```',
        expected_ids=[0, 1],
    )
    assert out == {0: "hi", 1: "there"}


def test_semantic_chunking_parse_batch_translation_raises_on_missing_ids() -> None:
    with pytest.raises(ValueError):
        SemanticChunkingPass._parse_batch_translation("[0]: hi", expected_ids=[0, 1])
