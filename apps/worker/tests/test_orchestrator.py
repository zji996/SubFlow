from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from subflow.config import Settings
from subflow.models.project import Project, ProjectStatus, StageName, StageRun, StageRunStatus
from subflow.models.segment import ASRCorrectedSegment, ASRMergedChunk, ASRSegment, VADSegment
from subflow.pipeline.orchestrator import PipelineOrchestrator
from subflow.pipeline.stage_runners import RUNNERS
from subflow.storage.artifact_store import LocalArtifactStore


class _InMemoryProjectRepo:
    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}

    def add(self, project: Project) -> None:
        self._projects[str(project.id)] = project

    async def get(self, project_id: str) -> Project | None:
        return self._projects.get(str(project_id))

    async def update_status(
        self,
        project_id: str,
        status: str,
        current_stage: int | None = None,
        *,
        error_message: str | None = None,  # noqa: ARG002
    ) -> None:
        project = self._projects.get(str(project_id))
        if project is None:
            return
        project.status = ProjectStatus(str(status))
        if current_stage is not None:
            project.current_stage = int(current_stage)


class _InMemoryStageRunRepo:
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], StageRun] = {}

    async def list_by_project(self, project_id: str) -> list[StageRun]:
        pid = str(project_id)
        return [sr for (p, _s), sr in self._runs.items() if p == pid]

    async def get(self, project_id: str, stage: str) -> StageRun | None:
        return self._runs.get((str(project_id), str(stage)))

    async def mark_running(self, project_id: str, stage: str) -> StageRun:
        sr = StageRun(stage=StageName(str(stage)), status=StageRunStatus.RUNNING)
        self._runs[(str(project_id), str(stage))] = sr
        return sr

    async def set_progress(
        self,
        project_id: str,
        stage: str,
        *,
        progress: int,  # noqa: ARG002
        message: str,  # noqa: ARG002
    ) -> None:
        return None

    async def mark_completed(self, project_id: str, stage: str, metadata=None) -> StageRun:  # noqa: ANN001
        sr = self._runs.get((str(project_id), str(stage)))
        if sr is None:
            sr = StageRun(stage=StageName(str(stage)))
            self._runs[(str(project_id), str(stage))] = sr
        sr.status = StageRunStatus.COMPLETED
        if isinstance(metadata, dict):
            sr.output_artifacts = dict(metadata.get("output_artifacts") or {})
        return sr

    async def mark_failed(
        self,
        project_id: str,
        stage: str,
        error_code: str,
        error_message: str,
        *,
        metadata=None,  # noqa: ANN001, ARG002
    ) -> StageRun:
        sr = self._runs.get((str(project_id), str(stage)))
        if sr is None:
            sr = StageRun(stage=StageName(str(stage)))
            self._runs[(str(project_id), str(stage))] = sr
        sr.status = StageRunStatus.FAILED
        sr.error_code = str(error_code)
        sr.error_message = str(error_message)
        return sr


class _InMemoryVADRepo:
    def __init__(self) -> None:
        self._segs: dict[str, list[VADSegment]] = {}

    async def delete_by_project(self, project_id: str) -> None:
        self._segs.pop(str(project_id), None)

    async def bulk_insert(self, project_id: str, segments: list[VADSegment]) -> None:
        self._segs[str(project_id)] = list(segments)

    async def get_by_project(self, project_id: str) -> list[VADSegment]:
        return list(self._segs.get(str(project_id), []))


class _InMemoryASRRepo:
    def __init__(self) -> None:
        self._segs: dict[str, list[ASRSegment]] = {}
        self._corrected: dict[str, dict[int, str]] = {}

    async def delete_by_project(self, project_id: str) -> None:
        self._segs.pop(str(project_id), None)
        self._corrected.pop(str(project_id), None)

    async def bulk_insert(self, project_id: str, segments: list[ASRSegment]) -> None:
        self._segs[str(project_id)] = list(segments)

    async def update_corrected_texts(self, project_id: str, corrections: dict[int, str]) -> None:
        self._corrected[str(project_id)] = {int(k): str(v) for k, v in dict(corrections or {}).items()}

    async def get_corrected_map(self, project_id: str) -> dict[int, str]:
        return dict(self._corrected.get(str(project_id), {}))

    async def get_by_project(self, project_id: str, *, use_corrected: bool = False) -> list[ASRSegment]:
        out: list[ASRSegment] = []
        corrected = self._corrected.get(str(project_id), {})
        for seg in list(self._segs.get(str(project_id), [])):
            text = seg.text
            if use_corrected and int(seg.id) in corrected:
                text = corrected[int(seg.id)]
            out.append(ASRSegment(id=seg.id, start=seg.start, end=seg.end, text=text, language=seg.language))
        return out


class _NoopRepo:
    async def delete(self, project_id: str) -> None:  # noqa: ARG002
        return None

    async def save(self, project_id: str, context):  # noqa: ANN001, ARG002
        return None

    async def delete_by_project(self, project_id: str) -> None:  # noqa: ARG002
        return None

    async def bulk_insert(self, project_id: str, chunks):  # noqa: ANN001, ARG002
        return []

    async def bulk_upsert(self, project_id: str, chunks):  # noqa: ANN001, ARG002
        return None

    async def get_by_project(self, project_id: str):  # noqa: ANN001, ARG002
        return []


@dataclass(frozen=True)
class _Runner:
    stage: StageName
    ctx_update: dict
    artifacts: dict[str, str]

    async def run(
        self,
        *,
        settings: Settings,  # noqa: ARG002
        store,  # noqa: ANN001, ARG002
        project_repo,  # noqa: ANN001, ARG002
        vad_repo,  # noqa: ANN001, ARG002
        asr_repo,  # noqa: ANN001, ARG002
        asr_merged_chunk_repo,  # noqa: ANN001, ARG002
        global_context_repo,  # noqa: ANN001, ARG002
        semantic_chunk_repo,  # noqa: ANN001, ARG002
        project,  # noqa: ANN001, ARG002
        ctx,  # noqa: ANN001
        progress_reporter=None,  # noqa: ANN001, ARG002
    ):
        return {**dict(ctx), **dict(self.ctx_update)}, dict(self.artifacts)


async def test_orchestrator_runs_up_to_target_stage(tmp_path, monkeypatch) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )
    store = LocalArtifactStore(str(tmp_path / "store"))

    project = Project(id="p1", name="n", media_url=str(tmp_path / "x.mp4"))
    project_repo = _InMemoryProjectRepo()
    project_repo.add(project)
    stage_run_repo = _InMemoryStageRunRepo()
    vad_repo = _InMemoryVADRepo()
    asr_repo = _InMemoryASRRepo()
    noop = _NoopRepo()

    # Stage 1 writes stage1.json (still persisted to ArtifactStore)
    stage1_ident = await store.save_json(
        project.id,
        StageName.AUDIO_PREPROCESS.value,
        "stage1.json",
        {
            "video_path": str(tmp_path / "input.mp4"),
            "audio_path": str(tmp_path / "audio.wav"),
            "vocals_audio_path": str(tmp_path / "vocals.wav"),
        },
    )
    monkeypatch.setitem(
        RUNNERS,
        StageName.AUDIO_PREPROCESS,
        _Runner(
            stage=StageName.AUDIO_PREPROCESS,
            ctx_update={
                "video_path": str(tmp_path / "input.mp4"),
                "audio_path": str(tmp_path / "audio.wav"),
                "vocals_audio_path": str(tmp_path / "vocals.wav"),
            },
            artifacts={"stage1.json": stage1_ident},
        ),
    )

    # Stage 2 persists VAD segments into repo (artifacts empty)
    class _VADRunner:
        async def run(
            self,
            *,
            settings: Settings,  # noqa: ARG002
            store,  # noqa: ANN001, ARG002
            project_repo,  # noqa: ANN001, ARG002
            vad_repo: _InMemoryVADRepo,
            asr_repo,  # noqa: ANN001, ARG002
            asr_merged_chunk_repo,  # noqa: ANN001, ARG002
            global_context_repo,  # noqa: ANN001, ARG002
            semantic_chunk_repo,  # noqa: ANN001, ARG002
            project: Project,
            ctx: dict,
            progress_reporter=None,  # noqa: ANN001, ARG002
        ):
            segs = [VADSegment(start=0.0, end=1.0)]
            await vad_repo.bulk_insert(project.id, segs)
            out = dict(ctx)
            out["vad_segments"] = segs
            return out, {}

    monkeypatch.setitem(RUNNERS, StageName.VAD, _VADRunner())

    orchestrator = PipelineOrchestrator(
        settings,
        store=store,
        project_repo=project_repo,
        stage_run_repo=stage_run_repo,
        vad_repo=vad_repo,
        asr_repo=asr_repo,
        asr_merged_chunk_repo=noop,
        global_context_repo=noop,
        semantic_chunk_repo=noop,
    )

    project, ctx = await orchestrator.run_stage(project, StageName.VAD)

    assert project.current_stage == 2
    assert "vad_segments" in ctx
    assert vad_repo._segs["p1"][0].start == 0.0
    sr1 = await stage_run_repo.get("p1", StageName.AUDIO_PREPROCESS.value)
    assert sr1 is not None
    assert Path(sr1.output_artifacts["stage1.json"]).exists()


async def test_orchestrator_skips_when_already_completed(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )
    store = LocalArtifactStore(str(tmp_path / "store"))

    project = Project(id="p1", name="n", media_url=str(tmp_path / "x.mp4"), current_stage=2)
    project_repo = _InMemoryProjectRepo()
    project_repo.add(project)
    stage_run_repo = _InMemoryStageRunRepo()
    vad_repo = _InMemoryVADRepo()
    asr_repo = _InMemoryASRRepo()
    noop = _NoopRepo()

    await store.save_json(
        project.id,
        StageName.AUDIO_PREPROCESS.value,
        "stage1.json",
        {"video_path": "v.mp4", "audio_path": "a.wav", "vocals_audio_path": "vocals.wav"},
    )
    await vad_repo.bulk_insert(project.id, [VADSegment(start=0.0, end=1.0)])

    orchestrator = PipelineOrchestrator(
        settings,
        store=store,
        project_repo=project_repo,
        stage_run_repo=stage_run_repo,
        vad_repo=vad_repo,
        asr_repo=asr_repo,
        asr_merged_chunk_repo=noop,
        global_context_repo=noop,
        semantic_chunk_repo=noop,
    )

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

    project = Project(id="p1", name="n", media_url=str(tmp_path / "x.mp4"))
    project_repo = _InMemoryProjectRepo()
    project_repo.add(project)
    stage_run_repo = _InMemoryStageRunRepo()
    vad_repo = _InMemoryVADRepo()
    asr_repo = _InMemoryASRRepo()
    noop = _NoopRepo()

    stage1_ident = await store.save_json(
        project.id,
        StageName.AUDIO_PREPROCESS.value,
        "stage1.json",
        {
            "video_path": str(tmp_path / "input.mp4"),
            "audio_path": str(tmp_path / "audio.wav"),
            "vocals_audio_path": str(tmp_path / "vocals.wav"),
        },
    )
    monkeypatch.setitem(
        RUNNERS,
        StageName.AUDIO_PREPROCESS,
        _Runner(
            stage=StageName.AUDIO_PREPROCESS,
            ctx_update={
                "video_path": str(tmp_path / "input.mp4"),
                "audio_path": str(tmp_path / "audio.wav"),
                "vocals_audio_path": str(tmp_path / "vocals.wav"),
            },
            artifacts={"stage1.json": stage1_ident},
        ),
    )

    class _VADRunner:
        async def run(
            self,
            *,
            settings: Settings,  # noqa: ARG002
            store,  # noqa: ANN001, ARG002
            project_repo,  # noqa: ANN001, ARG002
            vad_repo: _InMemoryVADRepo,
            asr_repo,  # noqa: ANN001, ARG002
            asr_merged_chunk_repo,  # noqa: ANN001, ARG002
            global_context_repo,  # noqa: ANN001, ARG002
            semantic_chunk_repo,  # noqa: ANN001, ARG002
            project: Project,
            ctx: dict,
            progress_reporter=None,  # noqa: ANN001, ARG002
        ):
            segs = [VADSegment(start=0.0, end=1.0)]
            await vad_repo.bulk_insert(project.id, segs)
            out = dict(ctx)
            out["vad_segments"] = segs
            out["vad_regions"] = segs
            return out, {}

    class _ASRRunner:
        async def run(
            self,
            *,
            settings: Settings,  # noqa: ARG002
            store: LocalArtifactStore,
            project_repo,  # noqa: ANN001, ARG002
            vad_repo,  # noqa: ANN001, ARG002
            asr_repo: _InMemoryASRRepo,
            asr_merged_chunk_repo,  # noqa: ANN001, ARG002
            global_context_repo,  # noqa: ANN001, ARG002
            semantic_chunk_repo,  # noqa: ANN001, ARG002
            project: Project,
            ctx: dict,
            progress_reporter=None,  # noqa: ANN001, ARG002
        ):
            segs = [ASRSegment(id=0, start=0.0, end=1.0, text="hello", language="en")]
            await asr_repo.bulk_insert(project.id, segs)
            merged = [
                ASRMergedChunk(
                    region_id=0,
                    chunk_id=0,
                    start=0.0,
                    end=1.0,
                    segment_ids=[0],
                    text="hello",
                )
            ]
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
            out = dict(ctx)
            out["asr_segments"] = segs
            out["asr_merged_chunks"] = merged
            out["full_transcript"] = "hello"
            return out, {"asr_merged_chunks.json": merged_ident}

    class _CorrectionRunner:
        async def run(
            self,
            *,
            settings: Settings,  # noqa: ARG002
            store,  # noqa: ANN001, ARG002
            project_repo,  # noqa: ANN001, ARG002
            vad_repo,  # noqa: ANN001, ARG002
            asr_repo: _InMemoryASRRepo,
            asr_merged_chunk_repo,  # noqa: ANN001, ARG002
            global_context_repo,  # noqa: ANN001, ARG002
            semantic_chunk_repo,  # noqa: ANN001, ARG002
            project: Project,
            ctx: dict,
            progress_reporter=None,  # noqa: ANN001, ARG002
        ):
            out = dict(ctx)
            out["asr_corrected_segments"] = {
                0: ASRCorrectedSegment(id=0, asr_segment_id=0, text="hello"),
            }
            await asr_repo.update_corrected_texts(project.id, {0: "hello"})
            return out, {}

    monkeypatch.setitem(RUNNERS, StageName.VAD, _VADRunner())
    monkeypatch.setitem(RUNNERS, StageName.ASR, _ASRRunner())
    monkeypatch.setitem(RUNNERS, StageName.LLM_ASR_CORRECTION, _CorrectionRunner())

    orchestrator = PipelineOrchestrator(
        settings,
        store=store,
        project_repo=project_repo,
        stage_run_repo=stage_run_repo,
        vad_repo=vad_repo,
        asr_repo=asr_repo,
        asr_merged_chunk_repo=noop,
        global_context_repo=noop,
        semantic_chunk_repo=noop,
    )

    project, _ctx = await orchestrator.run_stage(project, StageName.LLM_ASR_CORRECTION)

    assert project.current_stage == 4
    assert asr_repo._corrected["p1"][0] == "hello"
