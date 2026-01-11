from __future__ import annotations

import json

import pytest

from subflow.config import Settings
from subflow.models.segment import ASRSegment, VADSegment
from subflow.stages.base_llm import BaseLLMStage
from subflow.stages.llm_passes import SemanticChunkingPass


class _StatelessJsonHelper:
    async def complete_json(self, messages):  # noqa: ANN001
        user = next(m.content for m in messages if getattr(m, "role", "") == "user")
        payload_raw = user.split("\nASR 段落：\n", 1)[1]
        payload = json.loads(payload_raw)
        rel_ids = [int(x["id"]) for x in payload]
        return {
            "translation": "T",
            "translation_chunks": [{"text": "T", "segment_ids": rel_ids}],
        }


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
async def test_semantic_chunking_pass_partitions_and_reassigns_chunk_ids(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        _env_file=None,
        artifact_store_backend="local",
        data_dir=str(tmp_path / "data"),
        models_dir=str(tmp_path / "models"),
        log_dir=str(tmp_path / "logs"),
        concurrency={"llm_fast": 10, "llm_power": 10, "asr": 1},
        parallel={"enabled": True, "min_gap_seconds": 1.0},
    )

    stage = SemanticChunkingPass.__new__(SemanticChunkingPass)
    stage.settings = settings
    stage.profile = "power"
    stage.api_key = "x"
    stage.json_helper = _StatelessJsonHelper()

    ctx = await stage.execute(
        {
            "asr_segments": [
                ASRSegment(id=i, start=float(i), end=float(i + 1), text=f"t{i}")
                for i in range(6)
            ],
            "vad_regions": [
                VADSegment(start=0.0, end=2.9),
                VADSegment(start=3.95, end=6.0),
            ],
            "target_language": "zh",
            "global_context": {"topic": "x"},
        }
    )

    chunks = list(ctx.get("semantic_chunks") or [])
    assert [c.id for c in chunks] == [0, 1]
    assert [c.asr_segment_ids for c in chunks] == [[0, 1, 2], [3, 4, 5]]
