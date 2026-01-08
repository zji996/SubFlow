from __future__ import annotations

from subflow.config import Settings
from subflow.models.segment import ASRSegment
from subflow.stages.llm_passes import SemanticChunkingPass


class _StubJsonHelper:
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls = 0

    async def complete_json(self, _messages):  # noqa: ANN001
        self.calls += 1
        return self._responses.pop(0)


def _settings(tmp_path, *, api_key: str = "x") -> Settings:
    return Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
        llm_power={"api_key": api_key},
        llm_fast={"api_key": api_key},
    )


async def test_semantic_chunking_expands_window_when_requested(tmp_path) -> None:
    settings = _settings(tmp_path)
    stage = SemanticChunkingPass(settings)
    stage.json_helper = _StubJsonHelper(
        [
            {"need_more_context": {"reason": "cut off", "additional_segments": 4}},
            {
                "translation": "T",
                "translation_chunks": [
                    {"text": "T", "segment_ids": list(range(10))},
                ],
            },
        ]
    )

    ctx = await stage.execute(
        {
            "asr_segments": [
                ASRSegment(id=i, start=float(i), end=float(i + 1), text=f"t{i}")
                for i in range(10)
            ],
            "target_language": "zh",
        }
    )

    chunks = list(ctx.get("semantic_chunks") or [])
    assert len(chunks) == 1
    assert chunks[0].asr_segment_ids == list(range(10))
    assert stage.json_helper.calls == 2


async def test_semantic_chunking_forces_output_at_max_window(tmp_path) -> None:
    settings = _settings(tmp_path)
    stage = SemanticChunkingPass(settings)
    stage.json_helper = _StubJsonHelper(
        [
            {"need_more_context": {"reason": "need more", "additional_segments": 100}},
            {"need_more_context": {"reason": "still need more", "additional_segments": 5}},
            {
                "translation": "T",
                "translation_chunks": [
                    {"text": "T", "segment_ids": list(range(15))},
                ],
            },
        ]
    )

    ctx = await stage.execute(
        {
            "asr_segments": [
                ASRSegment(id=i, start=float(i), end=float(i + 1), text=f"t{i}")
                for i in range(15)
            ],
            "target_language": "zh",
        }
    )

    chunks = list(ctx.get("semantic_chunks") or [])
    assert len(chunks) == 1
    assert chunks[0].asr_segment_ids == list(range(15))
    assert stage.json_helper.calls == 3
