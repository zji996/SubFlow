from __future__ import annotations

import pytest

from subflow.config import Settings
from subflow.models.segment import ASRSegment
from subflow.stages.base_llm import BaseLLMStage
from subflow.stages.llm_passes import SemanticChunkingPass


class _DummyLLMStage(BaseLLMStage):
    name = "dummy_llm"
    profile_attr = "semantic_translation"

    def validate_input(self, context) -> bool:  # noqa: ANN001
        return True

    async def execute(self, context, progress_reporter=None):  # noqa: ANN001
        return context


def test_base_llm_stage_get_concurrency_limit_selects_by_profile(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        _env_file=None,
        artifact_store_backend="local",
        data_dir=str(tmp_path / "data"),
        models_dir=str(tmp_path / "models"),
        log_dir=str(tmp_path / "logs"),
        concurrency={"llm_fast": 11, "llm_power": 3, "asr": 1},
    )

    stage = _DummyLLMStage.__new__(_DummyLLMStage)
    stage.profile = "power"
    assert stage.get_concurrency_limit(settings) == 3
    stage.profile = "fast"
    assert stage.get_concurrency_limit(settings) == 11


@pytest.mark.asyncio
async def test_semantic_chunking_pass_fallback_is_one_to_one(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        _env_file=None,
        artifact_store_backend="local",
        data_dir=str(tmp_path / "data"),
        models_dir=str(tmp_path / "models"),
        log_dir=str(tmp_path / "logs"),
        concurrency={"llm_fast": 10, "llm_power": 10, "asr": 1},
    )

    stage = SemanticChunkingPass.__new__(SemanticChunkingPass)
    stage.settings = settings
    stage.profile = "power"
    stage.api_key = ""

    ctx = await stage.execute(
        {
            "asr_segments": [
                ASRSegment(id=i, start=float(i), end=float(i + 1), text=f"t{i}") for i in range(6)
            ],
            "target_language": "zh",
            "global_context": {"topic": "x"},
        }
    )

    chunks = list(ctx.get("semantic_chunks") or [])
    assert [c.id for c in chunks] == [0, 1, 2, 3, 4, 5]
    assert [c.asr_segment_ids for c in chunks] == [[0], [1], [2], [3], [4], [5]]
