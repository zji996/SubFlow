from __future__ import annotations

from dataclasses import dataclass

import pytest

from subflow.models.project import Project
from subflow.models.segment import (
    ASRCorrectedSegment,
    ASRMergedChunk,
    ASRSegment,
    SemanticChunk,
    TranslationChunk,
    VADSegment,
)
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


class _FakeVADRepo:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.inserted: dict[str, list[VADSegment]] = {}

    async def delete_by_project(self, project_id: str) -> None:
        self.deleted.append(str(project_id))
        self.inserted.pop(str(project_id), None)

    async def bulk_insert(self, project_id: str, segments: list[VADSegment]) -> None:
        self.inserted[str(project_id)] = list(segments)


class _FakeASRRepo:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.inserted: dict[str, list[ASRSegment]] = {}
        self.corrected: dict[str, dict[int, str]] = {}

    async def delete_by_project(self, project_id: str) -> None:
        self.deleted.append(str(project_id))
        self.inserted.pop(str(project_id), None)
        self.corrected.pop(str(project_id), None)

    async def bulk_insert(self, project_id: str, segments: list[ASRSegment]) -> None:
        self.inserted[str(project_id)] = list(segments)

    async def update_corrected_texts(self, project_id: str, corrections: dict[int, str]) -> None:
        self.corrected[str(project_id)] = {
            int(k): str(v) for k, v in dict(corrections or {}).items()
        }


class _FakeGlobalContextRepo:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.saved: dict[str, dict] = {}

    async def delete(self, project_id: str) -> None:
        self.deleted.append(str(project_id))
        self.saved.pop(str(project_id), None)

    async def save(self, project_id: str, context: dict) -> None:
        self.saved[str(project_id)] = dict(context)


class _FakeSemanticChunkRepo:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.saved: dict[str, list[SemanticChunk]] = {}

    async def delete_by_project(self, project_id: str) -> None:
        self.deleted.append(str(project_id))
        self.saved.pop(str(project_id), None)

    async def bulk_insert(self, project_id: str, chunks: list[SemanticChunk]) -> list[int]:
        self.saved[str(project_id)] = list(chunks)
        return list(range(len(chunks)))


class _FakeProjectRepo:
    def __init__(self) -> None:
        self.media_files: dict[str, dict[str, object]] = {}

    async def update_media_files(self, project_id: str, media_files: dict[str, object]) -> None:
        self.media_files[str(project_id)] = dict(media_files or {})


class _FakeASRMergedChunkRepo:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.upserted: dict[str, list[ASRMergedChunk]] = {}

    async def delete_by_project(self, project_id: str) -> None:
        self.deleted.append(str(project_id))
        self.upserted.pop(str(project_id), None)

    async def bulk_upsert(self, project_id: str, chunks: list[ASRMergedChunk]) -> None:
        self.upserted[str(project_id)] = list(chunks)


@dataclass
class _FakeStage:
    ctx_update: dict
    closed: bool = False

    async def execute(self, ctx, progress_reporter=None):
        return {**dict(ctx), **self.ctx_update}

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_audio_preprocess_runner_persists_media_files(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    runner = AudioPreprocessRunner()
    project = Project(id="p1", name="n", media_url="u", target_language="zh")
    project_repo = _FakeProjectRepo()
    vad_repo = _FakeVADRepo()
    asr_repo = _FakeASRRepo()
    asr_merged_chunk_repo = _FakeASRMergedChunkRepo()
    global_context_repo = _FakeGlobalContextRepo()
    semantic_chunk_repo = _FakeSemanticChunkRepo()

    stage = _FakeStage(
        {"video_path": "v.mp4", "audio_path": "a.wav", "vocals_audio_path": "vocals.wav"}
    )
    monkeypatch.setattr("subflow.pipeline.stage_runners.AudioPreprocessStage", lambda _s: stage)

    ctx, artifacts = await runner.run(
        settings=settings,
        store=store,
        project_repo=project_repo,
        vad_repo=vad_repo,
        asr_repo=asr_repo,
        asr_merged_chunk_repo=asr_merged_chunk_repo,
        global_context_repo=global_context_repo,
        semantic_chunk_repo=semantic_chunk_repo,
        project=project,
        ctx={},
    )
    assert artifacts == {}
    assert ctx["audio_path"] == "a.wav"
    assert store.saved == []
    assert "audio" in project_repo.media_files["p1"]


@pytest.mark.asyncio
async def test_vad_runner_persists_regions_to_repo(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    runner = VADRunner()
    project = Project(id="p1", name="n", media_url="u", target_language="zh")
    project_repo = _FakeProjectRepo()
    vad_repo = _FakeVADRepo()
    asr_repo = _FakeASRRepo()
    asr_merged_chunk_repo = _FakeASRMergedChunkRepo()
    global_context_repo = _FakeGlobalContextRepo()
    semantic_chunk_repo = _FakeSemanticChunkRepo()
    stage = _FakeStage(
        {
            "vad_regions": [VADSegment(start=0.0, end=2.0)],
        }
    )
    monkeypatch.setattr("subflow.pipeline.stage_runners.VADStage", lambda _s: stage)

    _ctx, artifacts = await runner.run(
        settings=settings,
        store=store,
        project_repo=project_repo,
        vad_repo=vad_repo,
        asr_repo=asr_repo,
        asr_merged_chunk_repo=asr_merged_chunk_repo,
        global_context_repo=global_context_repo,
        semantic_chunk_repo=semantic_chunk_repo,
        project=project,
        ctx={},
    )
    assert artifacts == {}
    assert vad_repo.inserted["p1"][0].start == 0.0
    assert vad_repo.inserted["p1"][0].end == 2.0
    assert vad_repo.inserted["p1"][0].region_id == 0


@pytest.mark.asyncio
async def test_asr_runner_persists_segments_transcript_and_merged(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    runner = ASRRunner()
    project = Project(id="p1", name="n", media_url="u", target_language="zh")
    project_repo = _FakeProjectRepo()
    vad_repo = _FakeVADRepo()
    asr_repo = _FakeASRRepo()
    asr_merged_chunk_repo = _FakeASRMergedChunkRepo()
    global_context_repo = _FakeGlobalContextRepo()
    semantic_chunk_repo = _FakeSemanticChunkRepo()
    stage = _FakeStage(
        {
            "asr_segments": [ASRSegment(id=0, start=0.0, end=1.0, text="hi", language="en")],
            "full_transcript": "hi",
            "asr_merged_chunks": [
                ASRMergedChunk(
                    region_id=0, chunk_id=0, start=0.0, end=1.0, segment_ids=[0], text="hi"
                )
            ],
        }
    )
    monkeypatch.setattr("subflow.pipeline.stage_runners.ASRStage", lambda _s: stage)

    _ctx, artifacts = await runner.run(
        settings=settings,
        store=store,
        project_repo=project_repo,
        vad_repo=vad_repo,
        asr_repo=asr_repo,
        asr_merged_chunk_repo=asr_merged_chunk_repo,
        global_context_repo=global_context_repo,
        semantic_chunk_repo=semantic_chunk_repo,
        project=project,
        ctx={},
    )
    assert artifacts == {}
    assert store.saved == []
    assert asr_repo.inserted["p1"][0].text == "hi"
    assert asr_merged_chunk_repo.upserted["p1"][0].text == "hi"


@pytest.mark.asyncio
async def test_llm_asr_correction_runner_persists_corrected_segments(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    runner = LLMASRCorrectionRunner()
    project = Project(id="p1", name="n", media_url="u", target_language="zh")
    project_repo = _FakeProjectRepo()
    vad_repo = _FakeVADRepo()
    asr_repo = _FakeASRRepo()
    asr_merged_chunk_repo = _FakeASRMergedChunkRepo()
    global_context_repo = _FakeGlobalContextRepo()
    semantic_chunk_repo = _FakeSemanticChunkRepo()
    stage = _FakeStage(
        {
            "asr_corrected_segments": {
                0: ASRCorrectedSegment(id=0, asr_segment_id=0, text="hi"),
            }
        }
    )
    monkeypatch.setattr("subflow.pipeline.stage_runners.LLMASRCorrectionStage", lambda _s: stage)

    _ctx, artifacts = await runner.run(
        settings=settings,
        store=store,
        project_repo=project_repo,
        vad_repo=vad_repo,
        asr_repo=asr_repo,
        asr_merged_chunk_repo=asr_merged_chunk_repo,
        global_context_repo=global_context_repo,
        semantic_chunk_repo=semantic_chunk_repo,
        project=project,
        ctx={},
    )
    assert artifacts == {}
    assert asr_repo.corrected["p1"][0] == "hi"


@pytest.mark.asyncio
async def test_llm_runner_truncates_asr_segments(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    runner = LLMRunner()
    project = Project(id="p1", name="n", media_url="u", target_language="zh")
    project_repo = _FakeProjectRepo()
    vad_repo = _FakeVADRepo()
    asr_repo = _FakeASRRepo()
    asr_merged_chunk_repo = _FakeASRMergedChunkRepo()
    global_context_repo = _FakeGlobalContextRepo()
    semantic_chunk_repo = _FakeSemanticChunkRepo()

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
                    translation_chunks=[TranslationChunk(text="甲", segment_id=0)],
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

    ctx_out, artifacts = await runner.run(
        settings=settings,
        store=store,
        project_repo=project_repo,
        vad_repo=vad_repo,
        asr_repo=asr_repo,
        asr_merged_chunk_repo=asr_merged_chunk_repo,
        global_context_repo=global_context_repo,
        semantic_chunk_repo=semantic_chunk_repo,
        project=project,
        ctx=ctx_in,
    )
    assert len(ctx_out["asr_segments"]) == 1
    assert artifacts == {}
    assert global_context_repo.saved["p1"]["topic"] == "t"
