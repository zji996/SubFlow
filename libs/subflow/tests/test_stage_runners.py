from __future__ import annotations

from dataclasses import dataclass

import pytest

from subflow.models.project import Project
from subflow.models.segment import ASRCorrectedSegment, ASRMergedChunk, ASRSegment, SemanticChunk, TranslationChunk, VADSegment
from subflow.pipeline.stage_runners import (
    ASRRunner,
    AudioPreprocessRunner,
    LLMASRCorrectionRunner,
    LLMRunner,
    VADRunner,
)
from subflow.storage.artifact_store import ArtifactStore


class InMemoryArtifactStore(ArtifactStore):
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str, bytes]] = []
        self._data: dict[tuple[str, str, str], bytes] = {}

    async def save(self, project_id: str, stage: str, name: str, data: bytes) -> str:
        key = (str(project_id), str(stage), str(name))
        payload = bytes(data)
        self.saved.append((key[0], key[1], key[2], payload))
        self._data[key] = payload
        return f"mem://{project_id}/{stage}/{name}"

    async def load(self, project_id: str, stage: str, name: str) -> bytes:
        key = (str(project_id), str(stage), str(name))
        if key not in self._data:
            raise FileNotFoundError(name)
        return self._data[key]

    async def list(self, project_id: str, stage: str | None = None) -> list[str]:
        return []


@dataclass
class _FakeStage:
    ctx_update: dict
    closed: bool = False

    async def execute(self, ctx, progress_reporter=None):
        return {**dict(ctx), **self.ctx_update}

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_audio_preprocess_runner_persists_stage1(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    runner = AudioPreprocessRunner()
    project = Project(id="p1", name="n", media_url="u", target_language="zh")

    stage = _FakeStage({"video_path": "v.mp4", "audio_path": "a.wav", "vocals_audio_path": "vocals.wav"})
    monkeypatch.setattr("subflow.pipeline.stage_runners.AudioPreprocessStage", lambda _s: stage)

    ctx, artifacts = await runner.run(settings=settings, store=store, project=project, ctx={})
    assert artifacts["stage1.json"].startswith("mem://")
    assert ctx["audio_path"] == "a.wav"
    assert any(name == "stage1.json" for _pid, _st, name, _payload in store.saved)


@pytest.mark.asyncio
async def test_vad_runner_persists_segments_and_regions(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    runner = VADRunner()
    project = Project(id="p1", name="n", media_url="u", target_language="zh")
    stage = _FakeStage({"vad_segments": [VADSegment(start=0.0, end=1.0)], "vad_regions": [VADSegment(start=0.0, end=2.0)]})
    monkeypatch.setattr("subflow.pipeline.stage_runners.VADStage", lambda _s: stage)

    _ctx, artifacts = await runner.run(settings=settings, store=store, project=project, ctx={})
    assert "vad_segments.json" in artifacts
    assert "vad_regions.json" in artifacts


@pytest.mark.asyncio
async def test_asr_runner_persists_segments_transcript_and_merged(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    runner = ASRRunner()
    project = Project(id="p1", name="n", media_url="u", target_language="zh")
    stage = _FakeStage(
        {
            "asr_segments": [ASRSegment(id=0, start=0.0, end=1.0, text="hi", language="en")],
            "full_transcript": "hi",
            "asr_merged_chunks": [ASRMergedChunk(region_id=0, chunk_id=0, start=0.0, end=1.0, segment_ids=[0], text="hi")],
        }
    )
    monkeypatch.setattr("subflow.pipeline.stage_runners.ASRStage", lambda _s: stage)

    _ctx, artifacts = await runner.run(settings=settings, store=store, project=project, ctx={})
    assert set(artifacts.keys()) == {"asr_segments.json", "full_transcript.txt", "asr_merged_chunks.json"}


@pytest.mark.asyncio
async def test_llm_asr_correction_runner_persists_corrected_segments(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    runner = LLMASRCorrectionRunner()
    project = Project(id="p1", name="n", media_url="u", target_language="zh")
    stage = _FakeStage(
        {
            "asr_corrected_segments": {
                0: ASRCorrectedSegment(id=0, asr_segment_id=0, text="hi"),
            }
        }
    )
    monkeypatch.setattr("subflow.pipeline.stage_runners.LLMASRCorrectionStage", lambda _s: stage)

    _ctx, artifacts = await runner.run(settings=settings, store=store, project=project, ctx={})
    assert "asr_corrected_segments.json" in artifacts


@pytest.mark.asyncio
async def test_llm_runner_truncates_asr_segments(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    runner = LLMRunner()
    project = Project(id="p1", name="n", media_url="u", target_language="zh")

    settings.llm_limits.max_asr_segments = 1

    stage1 = _FakeStage({"global_context": {"topic": "t"}})
    stage2 = _FakeStage(
        {
            "semantic_chunks": [
                SemanticChunk(
                    id=0,
                    text="a",
                    translation="甲",
                    asr_segment_ids=[0],
                    translation_chunks=[TranslationChunk(text="甲", segment_ids=[0])],
                )
            ]
        }
    )
    monkeypatch.setattr("subflow.pipeline.stage_runners.GlobalUnderstandingPass", lambda _s: stage1)
    monkeypatch.setattr("subflow.pipeline.stage_runners.SemanticChunkingPass", lambda _s: stage2)

    ctx_in = {
        "asr_segments": [
            ASRSegment(id=0, start=0.0, end=1.0, text="a", language="en"),
            ASRSegment(id=1, start=1.0, end=2.0, text="b", language="en"),
        ],
        "asr_corrected_segments": {
            0: ASRCorrectedSegment(id=0, asr_segment_id=0, text="A"),
            1: ASRCorrectedSegment(id=1, asr_segment_id=1, text="B"),
        },
    }

    ctx_out, artifacts = await runner.run(settings=settings, store=store, project=project, ctx=ctx_in)
    assert len(ctx_out["asr_segments"]) == 1
    assert "semantic_chunks.json" in artifacts
    assert "global_context.json" in artifacts
