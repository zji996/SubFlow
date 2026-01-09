from __future__ import annotations

from pathlib import Path

from subflow.config import Settings
from subflow.models.project import Project, StageName
from subflow.models.segment import ASRCorrectedSegment, ASRMergedChunk, ASRSegment, VADSegment
from subflow.pipeline.orchestrator import PipelineOrchestrator
from subflow.pipeline.stage_runners import RUNNERS
from subflow.storage.artifact_store import LocalArtifactStore


async def test_orchestrator_runs_up_to_target_stage(tmp_path, monkeypatch) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )
    store = LocalArtifactStore(str(tmp_path / "store"))

    class _AudioRunner:
        async def run(self, *, settings: Settings, store, project, ctx, progress_reporter=None):  # noqa: ARG002
            out = dict(ctx)
            out["video_path"] = str(tmp_path / "input.mp4")
            out["audio_path"] = str(tmp_path / "audio.wav")
            out["vocals_audio_path"] = str(tmp_path / "vocals.wav")
            ident = await store.save_json(
                project.id,
                StageName.AUDIO_PREPROCESS.value,
                "stage1.json",
                {
                    "video_path": out["video_path"],
                    "audio_path": out["audio_path"],
                    "vocals_audio_path": out["vocals_audio_path"],
                },
            )
            return out, {"stage1.json": ident}

    class _VADRunner:
        async def run(self, *, settings: Settings, store, project, ctx, progress_reporter=None):  # noqa: ARG002
            out = dict(ctx)
            out["vad_segments"] = [VADSegment(start=0.0, end=1.0)]
            ident = await store.save_json(
                project.id,
                StageName.VAD.value,
                "vad_segments.json",
                [{"start": 0.0, "end": 1.0}],
            )
            return out, {"vad_segments.json": ident}

    monkeypatch.setitem(RUNNERS, StageName.AUDIO_PREPROCESS, _AudioRunner())
    monkeypatch.setitem(RUNNERS, StageName.VAD, _VADRunner())

    project = Project(id="p1", name="n", media_url=str(tmp_path / "x.mp4"))
    orchestrator = PipelineOrchestrator(settings, store=store)

    project, ctx = await orchestrator.run_stage(project, StageName.VAD)

    assert project.current_stage == 2
    assert "vad_segments" in ctx
    assert Path(project.artifacts[StageName.AUDIO_PREPROCESS.value]["stage1.json"]).exists()
    assert Path(project.artifacts[StageName.VAD.value]["vad_segments.json"]).exists()


async def test_orchestrator_skips_when_already_completed(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )
    store = LocalArtifactStore(str(tmp_path / "store"))

    project = Project(
        id="p1",
        name="n",
        media_url=str(tmp_path / "x.mp4"),
        current_stage=2,
    )

    await store.save_json(
        project.id,
        StageName.AUDIO_PREPROCESS.value,
        "stage1.json",
        {"video_path": "v.mp4", "audio_path": "a.wav", "vocals_audio_path": "vocals.wav"},
    )
    await store.save_json(
        project.id,
        StageName.VAD.value,
        "vad_segments.json",
        [{"start": 0.0, "end": 1.0}],
    )

    orchestrator = PipelineOrchestrator(settings, store=store)
    before_runs = len(project.stage_runs)
    project, ctx = await orchestrator.run_stage(project, StageName.VAD)

    assert len(project.stage_runs) == before_runs
    assert project.current_stage == 2
    assert ctx["vad_segments"][0].start == 0.0
    assert ctx["vad_segments"][0].end == 1.0


async def test_orchestrator_runs_llm_asr_correction_stage(tmp_path, monkeypatch) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
        llm={"api_key": ""},
    )
    store = LocalArtifactStore(str(tmp_path / "store"))

    class _AudioRunner:
        async def run(self, *, settings: Settings, store, project, ctx, progress_reporter=None):  # noqa: ARG002
            out = dict(ctx)
            out["video_path"] = str(tmp_path / "input.mp4")
            out["audio_path"] = str(tmp_path / "audio.wav")
            out["vocals_audio_path"] = str(tmp_path / "vocals.wav")
            ident = await store.save_json(
                project.id,
                StageName.AUDIO_PREPROCESS.value,
                "stage1.json",
                {
                    "video_path": out["video_path"],
                    "audio_path": out["audio_path"],
                    "vocals_audio_path": out["vocals_audio_path"],
                },
            )
            return out, {"stage1.json": ident}

    class _VADRunner:
        async def run(self, *, settings: Settings, store, project, ctx, progress_reporter=None):  # noqa: ARG002
            out = dict(ctx)
            out["vad_segments"] = [VADSegment(start=0.0, end=1.0)]
            out["vad_regions"] = [VADSegment(start=0.0, end=1.0)]
            seg_ident = await store.save_json(
                project.id,
                StageName.VAD.value,
                "vad_segments.json",
                [{"start": 0.0, "end": 1.0}],
            )
            reg_ident = await store.save_json(
                project.id,
                StageName.VAD.value,
                "vad_regions.json",
                [{"start": 0.0, "end": 1.0}],
            )
            return out, {"vad_segments.json": seg_ident, "vad_regions.json": reg_ident}

    class _ASRRunner:
        async def run(self, *, settings: Settings, store, project, ctx, progress_reporter=None):  # noqa: ARG002
            out = dict(ctx)
            out["asr_segments"] = [ASRSegment(id=0, start=0.0, end=1.0, text="hello", language="en")]
            out["full_transcript"] = "hello"
            out["asr_merged_chunks"] = [
                ASRMergedChunk(
                    region_id=0,
                    chunk_id=0,
                    start=0.0,
                    end=1.0,
                    segment_ids=[0],
                    text="hello",
                )
            ]
            asr_ident = await store.save_json(
                project.id,
                StageName.ASR.value,
                "asr_segments.json",
                [{"id": 0, "start": 0.0, "end": 1.0, "text": "hello", "language": "en"}],
            )
            merged_ident = await store.save_json(
                project.id,
                StageName.ASR.value,
                "asr_merged_chunks.json",
                [
                    {
                        "region_id": 0,
                        "chunk_id": 0,
                        "start": 0.0,
                        "end": 1.0,
                        "segment_ids": [0],
                        "text": "hello",
                    }
                ],
            )
            transcript_ident = await store.save_text(project.id, StageName.ASR.value, "full_transcript.txt", "hello")
            return out, {
                "asr_segments.json": asr_ident,
                "asr_merged_chunks.json": merged_ident,
                "full_transcript.txt": transcript_ident,
            }

    class _CorrectionRunner:
        async def run(self, *, settings: Settings, store, project, ctx, progress_reporter=None):  # noqa: ARG002
            out = dict(ctx)
            out["asr_corrected_segments"] = {
                0: ASRCorrectedSegment(id=0, asr_segment_id=0, text="hello"),
            }
            ident = await store.save_json(
                project.id,
                StageName.LLM_ASR_CORRECTION.value,
                "asr_corrected_segments.json",
                [{"id": 0, "asr_segment_id": 0, "text": "hello"}],
            )
            return out, {"asr_corrected_segments.json": ident}

    monkeypatch.setitem(RUNNERS, StageName.AUDIO_PREPROCESS, _AudioRunner())
    monkeypatch.setitem(RUNNERS, StageName.VAD, _VADRunner())
    monkeypatch.setitem(RUNNERS, StageName.ASR, _ASRRunner())
    monkeypatch.setitem(RUNNERS, StageName.LLM_ASR_CORRECTION, _CorrectionRunner())

    project = Project(id="p1", name="n", media_url=str(tmp_path / "x.mp4"))
    orchestrator = PipelineOrchestrator(settings, store=store)

    project, _ctx = await orchestrator.run_stage(project, StageName.LLM_ASR_CORRECTION)

    assert project.current_stage == 4
    assert Path(project.artifacts[StageName.AUDIO_PREPROCESS.value]["stage1.json"]).exists()
    assert Path(project.artifacts[StageName.VAD.value]["vad_segments.json"]).exists()
    assert Path(project.artifacts[StageName.ASR.value]["asr_segments.json"]).exists()
    assert Path(project.artifacts[StageName.ASR.value]["asr_merged_chunks.json"]).exists()
    assert Path(project.artifacts[StageName.LLM_ASR_CORRECTION.value]["asr_corrected_segments.json"]).exists()
