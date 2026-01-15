from __future__ import annotations

from subflow.config import Settings
from subflow.models.segment import ASRSegment
from subflow.stages.llm_passes import SemanticChunkingPass


async def test_semantic_chunking_outputs_one_translation_per_segment_without_api_key() -> None:
    settings = Settings(llm_fast={"api_key": ""}, llm_power={"api_key": ""})
    stage = SemanticChunkingPass(settings)

    out = await stage.execute(
        {
            "target_language": "zh",
            "asr_segments": [
                ASRSegment(id=0, start=0.0, end=1.0, text="hello"),
                ASRSegment(id=1, start=1.0, end=2.0, text=""),
                ASRSegment(id=2, start=2.0, end=3.0, text="world"),
            ],
        }
    )

    assert [c.asr_segment_ids for c in out["semantic_chunks"]] == [[0], [2]]
    assert [t.segment_id for t in out["segment_translations"]] == [0, 2]
    assert out["segment_translations"][0].translation == "[zh] hello"
