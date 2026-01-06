from __future__ import annotations

from subflow.config import Settings
from subflow.stages.llm_passes import SemanticChunkingPass


def test_parse_result_converts_relative_ids_to_absolute() -> None:
    stage = SemanticChunkingPass(Settings())

    result = {
        "filler_segment_ids": [0, 1],
        "corrected_segments": [
            {
                "asr_segment_id": 2,
                "text": "我们今天聊人工智能",
                "corrections": [{"original": "人工只能", "corrected": "人工智能"}],
            }
        ],
        "chunk": {
            "text": "我们今天聊人工智能的应用场景",
            "translation": "Today we'll discuss AI application scenarios",
            "asr_segment_ids": [2, 3],
        },
        "next_cursor": 4,
    }

    filler_ids, corrected_map, chunk, next_cursor = stage._parse_result(
        result,
        window_start=10,
        window_len=6,
        chunk_id=7,
    )

    assert filler_ids == {10, 11}
    assert next_cursor == 14

    assert 12 in corrected_map
    assert corrected_map[12].text == "我们今天聊人工智能"
    assert corrected_map[12].corrections[0].original == "人工只能"
    assert corrected_map[12].corrections[0].corrected == "人工智能"

    assert chunk is not None
    assert chunk.id == 7
    assert chunk.asr_segment_ids == [12, 13]
    assert chunk.translation == "Today we'll discuss AI application scenarios"

