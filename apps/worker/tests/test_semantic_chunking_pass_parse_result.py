from __future__ import annotations

from subflow.config import Settings
from subflow.models.segment import ASRSegment
from subflow.stages.llm_passes import SemanticChunkingPass


def _make_window() -> list[ASRSegment]:
    return [
        ASRSegment(id=10, start=0.0, end=1.2, text="嗯"),
        ASRSegment(id=11, start=1.2, end=2.0, text="那个"),
        ASRSegment(id=12, start=2.0, end=3.6, text="我们今天聊人工只能"),
        ASRSegment(id=13, start=3.6, end=5.0, text="的应用场景"),
        ASRSegment(id=14, start=5.0, end=6.0, text="然后"),
        ASRSegment(id=15, start=6.0, end=7.0, text="继续"),
    ]


def test_parse_result_converts_relative_ids_to_absolute_and_applies_corrections() -> None:
    stage = SemanticChunkingPass(Settings())
    window = _make_window()

    result = {
        "filler_segment_ids": [0, 1],
        "corrected_segments": [
            {
                "asr_segment_id": 2,
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
        window_segments=window,
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


def test_parse_result_handles_missing_corrected_segments_key() -> None:
    stage = SemanticChunkingPass(Settings())
    window = _make_window()

    result = {
        "filler_segment_ids": [0, 1],
        "chunk": {
            "text": "我们今天聊人工只能的应用场景",
            "translation": "Today we'll discuss AI application scenarios",
            "asr_segment_ids": [2, 3],
        },
        "next_cursor": 4,
    }

    _, corrected_map, _, _ = stage._parse_result(
        result,
        window_start=10,
        window_segments=window,
        chunk_id=7,
    )

    assert corrected_map == {}


def test_parse_result_handles_empty_corrected_segments_array() -> None:
    stage = SemanticChunkingPass(Settings())
    window = _make_window()

    result = {
        "filler_segment_ids": [0, 1],
        "corrected_segments": [],
        "chunk": {
            "text": "我们今天聊人工只能的应用场景",
            "translation": "Today we'll discuss AI application scenarios",
            "asr_segment_ids": [2, 3],
        },
        "next_cursor": 4,
    }

    _, corrected_map, _, _ = stage._parse_result(
        result,
        window_start=10,
        window_segments=window,
        chunk_id=7,
    )

    assert corrected_map == {}


def test_parse_result_preserves_original_text_when_no_corrections() -> None:
    stage = SemanticChunkingPass(Settings())
    window = _make_window()

    result = {
        "corrected_segments": [{"asr_segment_id": 2, "corrections": []}],
        "chunk": {
            "text": "我们今天聊人工只能的应用场景",
            "translation": "Today we'll discuss AI application scenarios",
            "asr_segment_ids": [2, 3],
        },
        "next_cursor": 4,
    }

    _, corrected_map, _, _ = stage._parse_result(
        result,
        window_start=10,
        window_segments=window,
        chunk_id=7,
    )

    assert corrected_map[12].text == "我们今天聊人工只能"


def test_parse_result_ignores_out_of_window_ids() -> None:
    stage = SemanticChunkingPass(Settings())
    window = _make_window()

    result = {
        "filler_segment_ids": [999],
        "corrected_segments": [{"asr_segment_id": 999, "corrections": []}],
        "chunk": {
            "text": "x",
            "translation": "y",
            "asr_segment_ids": [999],
        },
        "next_cursor": 1,
    }

    filler_ids, corrected_map, chunk, _ = stage._parse_result(
        result,
        window_start=10,
        window_segments=window,
        chunk_id=1,
    )

    assert filler_ids == set()
    assert corrected_map == {}
    assert chunk is None
