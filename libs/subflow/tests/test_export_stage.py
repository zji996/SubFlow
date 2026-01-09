from __future__ import annotations

import pytest

from subflow.exceptions import ConfigurationError
from subflow.models.segment import ASRSegment, SemanticChunk, TranslationChunk
from subflow.stages.export import ExportStage


@pytest.mark.asyncio
async def test_export_stage_generates_subtitle_text(settings) -> None:
    stage = ExportStage(settings, format="srt", content="both", primary_position="top", translation_style="per_chunk")
    ctx = {
        "project_id": "proj_1",
        "asr_segments": [ASRSegment(id=0, start=0.0, end=1.0, text="a", language="en")],
        "semantic_chunks": [
            SemanticChunk(
                id=0,
                text="a",
                translation="甲",
                asr_segment_ids=[0],
                translation_chunks=[TranslationChunk(text="甲", segment_ids=[0])],
            )
        ],
    }
    out = await stage.execute(ctx)
    assert "subtitle_text" in out
    assert out["result_path"].endswith(".srt")
    assert "甲" in out["subtitle_text"]


@pytest.mark.asyncio
async def test_export_stage_rejects_unknown_format(settings) -> None:
    stage = ExportStage(settings, format="nope")
    ctx = {"project_id": "proj_1", "asr_segments": [ASRSegment(id=0, start=0.0, end=1.0, text="a", language="en")]}
    with pytest.raises(ConfigurationError, match="Unknown subtitle format"):
        await stage.execute(ctx)

