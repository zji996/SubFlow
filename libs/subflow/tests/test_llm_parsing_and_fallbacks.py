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


def test_semantic_chunking_parse_result_translation_chunks_relative_ids() -> None:
    stage = SemanticChunkingPass.__new__(SemanticChunkingPass)
    window_segments = [
        ASRSegment(id=10, start=0.0, end=1.0, text="a", language="en"),
        ASRSegment(id=11, start=1.0, end=2.0, text="b", language="en"),
    ]
    result = {
        "translation": "甲乙",
        "asr_segment_ids": [0, 1],
    }
    chunk, next_cursor = stage._parse_result(result, window_start=10, window_segments=window_segments, chunk_id=0)
    assert chunk is not None
    assert chunk.asr_segment_ids == [10, 11]
    assert next_cursor == 12
    assert chunk.translation_chunks and chunk.translation_chunks[0].segment_id == 10
    assert chunk.translation_chunks and chunk.translation_chunks[0].text == "甲"
