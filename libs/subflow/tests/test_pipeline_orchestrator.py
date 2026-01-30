from __future__ import annotations

from dataclasses import dataclass

import pytest

from subflow.error_codes import ErrorCode
from subflow.exceptions import StageExecutionError
from subflow.models.project import Project, ProjectStatus, StageName
from subflow.pipeline.orchestrator import PipelineOrchestrator, _StageRunProgressReporter
from subflow.storage.artifact_store import ArtifactStore


class InMemoryArtifactStore(ArtifactStore):
    def __init__(self) -> None:
        self._data: dict[tuple[str, str, str], bytes] = {}

    async def save(self, project_id: str, stage: str, name: str, data: bytes) -> str:
        key = (str(project_id), str(stage), str(name))
        self._data[key] = bytes(data)
        return f"mem://{project_id}/{stage}/{name}"

    async def load(self, project_id: str, stage: str, name: str) -> bytes:
        key = (str(project_id), str(stage), str(name))
        if key not in self._data:
            raise FileNotFoundError(name)
        return self._data[key]

    async def list(self, project_id: str, stage: str | None = None) -> list[str]:
        out: list[str] = []
        for pid, st, name in self._data.keys():
            if pid != project_id:
                continue
            if stage is not None and st != stage:
                continue
            out.append(f"mem://{pid}/{st}/{name}")
        return out

    async def delete_project(self, project_id: str) -> int:
        removed = 0
        for key in list(self._data.keys()):
            if key[0] == str(project_id):
                removed += 1
                self._data.pop(key, None)
        return removed

    async def list_project_ids(self) -> list[str]:
        return sorted({pid for (pid, _st, _name) in self._data.keys()})


class _InMemoryProjectRepo:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def get(self, project_id: str) -> Project | None:  # noqa: ARG002
        return self.project

    async def update_media_files(self, project_id: str, media_files: dict[str, object]) -> None:  # noqa: ARG002
        self.project.media_files = dict(media_files or {})

    async def update_status(
        self,
        project_id: str,  # noqa: ARG002
        status: str,
        current_stage: int | None = None,
        *,
        error_message: str | None = None,  # noqa: ARG002
    ) -> None:
        self.project.status = ProjectStatus(str(status))
        if current_stage is not None:
            self.project.current_stage = int(current_stage)


class _InMemoryStageRunRepo:
    def __init__(self) -> None:
        self.stage_runs: dict[tuple[str, str], object] = {}

    async def list_by_project(self, project_id: str) -> list:  # noqa: ANN001
        out: list = []
        for (pid, _stage), sr in self.stage_runs.items():
            if pid == project_id:
                out.append(sr)
        return out

    async def mark_running(self, project_id: str, stage: str):  # noqa: ANN001
        from subflow.models.project import StageRun, StageRunStatus

        sr = StageRun(stage=StageName(stage), status=StageRunStatus.RUNNING)
        self.stage_runs[(project_id, stage)] = sr
        return sr

    async def set_progress(
        self,
        project_id: str,
        stage: str,
        *,
        progress: int,
        message: str,
        metrics=None,  # noqa: ANN001, ARG002
    ) -> None:  # noqa: ARG002
        return None

    async def mark_completed(self, project_id: str, stage: str, metadata=None):  # noqa: ANN001, ARG002
        from subflow.models.project import StageRun, StageRunStatus

        sr = self.stage_runs.get((project_id, stage))
        if isinstance(sr, StageRun):
            sr.status = StageRunStatus.COMPLETED
            return sr
        sr2 = StageRun(stage=StageName(stage), status=StageRunStatus.COMPLETED)
        self.stage_runs[(project_id, stage)] = sr2
        return sr2

    async def mark_failed(
        self, project_id: str, stage: str, error_code: str, error_message: str, *, metadata=None
    ):  # noqa: ANN001, ARG002
        from subflow.models.project import StageRun, StageRunStatus

        sr = self.stage_runs.get((project_id, stage))
        if isinstance(sr, StageRun):
            sr.status = StageRunStatus.FAILED
            return sr
        sr2 = StageRun(stage=StageName(stage), status=StageRunStatus.FAILED)
        self.stage_runs[(project_id, stage)] = sr2
        return sr2

    async def reset_to_pending(self, project_id: str, stage: str):  # noqa: ANN001
        from subflow.models.project import StageRun, StageRunStatus

        sr = self.stage_runs.get((project_id, stage))
        if isinstance(sr, StageRun):
            sr.status = StageRunStatus.PENDING
            sr.started_at = None
            sr.completed_at = None
            sr.error_message = None
            sr.metrics = {}
            sr.output_artifacts = {}
            sr.input_artifacts = {}
            return sr
        sr2 = StageRun(stage=StageName(stage), status=StageRunStatus.PENDING)
        self.stage_runs[(project_id, stage)] = sr2
        return sr2


class _NoopRepo:
    async def delete_by_project(self, project_id: str) -> None:  # noqa: ARG002
        return None

    async def bulk_insert(self, project_id: str, segments):  # noqa: ANN001, ARG002
        return None

    async def update_corrected_texts(self, project_id: str, corrections):  # noqa: ANN001, ARG002
        return None

    async def clear_corrected_texts(self, project_id: str) -> None:  # noqa: ARG002
        return None

    async def get_by_project(self, project_id: str, **kwargs):  # noqa: ANN001, ARG002
        return []

    async def get_corrected_map(self, project_id: str) -> dict[int, str]:  # noqa: ARG002
        return {}

    async def save(self, project_id: str, context):  # noqa: ANN001, ARG002
        return None

    async def delete(self, project_id: str) -> None:  # noqa: ARG002
        return None


@dataclass(frozen=True)
class _Runner:
    stage: StageName
    fail: bool = False
    progress_steps: list[int] | None = None

    async def run(
        self,
        *,
        settings,  # noqa: ANN001
        store,  # noqa: ANN001
        project_repo,  # noqa: ANN001, ARG002
        vad_repo,  # noqa: ANN001, ARG002
        asr_repo,  # noqa: ANN001, ARG002
        asr_merged_chunk_repo,  # noqa: ANN001, ARG002
        global_context_repo,  # noqa: ANN001, ARG002
        semantic_chunk_repo,  # noqa: ANN001, ARG002
        project,  # noqa: ANN001, ARG002
        ctx,  # noqa: ANN001
        progress_reporter=None,  # noqa: ANN001
    ):
        if self.fail:
            raise RuntimeError("timed out")
        for pct in list(self.progress_steps or []):
            if progress_reporter is not None:
                await progress_reporter.report(int(pct), f"step {pct}")
        return dict(ctx), {"ok.txt": "mem://ok"}


@pytest.mark.asyncio
async def test_progress_reporter_rate_limits_by_percent_step() -> None:
    updates: list[int] = []

    async def _notify(_project: Project) -> None:
        updates.append(1)

    project = Project(id="p1", name="n", media_url="u", target_language="zh")
    from subflow.models.project import StageRun

    sr = StageRun(stage=StageName.ASR)
    project.stage_runs.append(sr)

    reporter = _StageRunProgressReporter(
        project=project,
        stage_run=sr,
        notify_update=_notify,
        min_percent_step=5,
        min_interval_s=0.0,
    )

    await reporter.report(1, "no")
    assert sr.progress is None
    assert not updates

    await reporter.report(5, "five")
    assert sr.progress == 5
    assert sr.progress_message == "five"
    assert len(updates) == 1

    await reporter.report(4, "backwards")
    assert sr.progress == 5
    assert len(updates) == 1

    await reporter.report(10, "ten")
    assert sr.progress == 10
    assert len(updates) == 2

    await reporter.report(200, "done")
    assert sr.progress == 100
    assert len(updates) == 3


@pytest.mark.asyncio
async def test_orchestrator_runs_and_marks_completed(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    updates: list[Project] = []

    async def on_update(p: Project) -> None:
        updates.append(p)

    project = Project(id="proj_1", name="demo", media_url="u", target_language="zh")
    project_repo = _InMemoryProjectRepo(project)
    stage_run_repo = _InMemoryStageRunRepo()
    noop = _NoopRepo()
    orch = PipelineOrchestrator(
        settings,
        store,
        project_repo=project_repo,
        stage_run_repo=stage_run_repo,
        vad_repo=noop,
        asr_repo=noop,
        asr_merged_chunk_repo=noop,
        global_context_repo=noop,
        semantic_chunk_repo=noop,
        on_project_update=on_update,
    )

    fake_runners = {
        s: _Runner(stage=s, progress_steps=[10, 100])
        for s in [
            StageName.AUDIO_PREPROCESS,
            StageName.VAD,
            StageName.ASR,
            StageName.LLM_ASR_CORRECTION,
            StageName.LLM,
        ]
    }
    monkeypatch.setattr("subflow.pipeline.orchestrator.RUNNERS", fake_runners, raising=False)

    out_project, ctx = await orch.run_stage(project, StageName.ASR)
    assert out_project.current_stage == 3
    assert out_project.status == ProjectStatus.PROCESSING
    assert len(out_project.stage_runs) >= 1
    assert ctx["project_id"] == "proj_1"
    assert updates

    out_project, _ = await orch.run_stage(out_project, StageName.LLM)
    assert out_project.status == ProjectStatus.COMPLETED
    assert out_project.current_stage == 5


@pytest.mark.asyncio
async def test_orchestrator_error_sets_failed_status_and_error_code(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    project = Project(id="proj_2", name="demo", media_url="u", target_language="zh")
    project_repo = _InMemoryProjectRepo(project)
    stage_run_repo = _InMemoryStageRunRepo()
    noop = _NoopRepo()
    orch = PipelineOrchestrator(
        settings,
        store,
        project_repo=project_repo,
        stage_run_repo=stage_run_repo,
        vad_repo=noop,
        asr_repo=noop,
        asr_merged_chunk_repo=noop,
        global_context_repo=noop,
        semantic_chunk_repo=noop,
    )

    fake_runners = {
        StageName.AUDIO_PREPROCESS: _Runner(stage=StageName.AUDIO_PREPROCESS),
        StageName.VAD: _Runner(stage=StageName.VAD),
        StageName.ASR: _Runner(stage=StageName.ASR, fail=True),
    }
    monkeypatch.setattr("subflow.pipeline.orchestrator.RUNNERS", fake_runners, raising=False)

    with pytest.raises(StageExecutionError):
        await orch.run_stage(project, StageName.ASR)
    assert project.status == ProjectStatus.FAILED
    assert project.stage_runs[-1].error_code == ErrorCode.ASR_FAILED.value


@pytest.mark.asyncio
async def test_orchestrator_retry_resets_failed_stage_and_clears_downstream_data(
    settings, monkeypatch
) -> None:
    store = InMemoryArtifactStore()
    project = Project(id="proj_retry", name="demo", media_url="u", target_language="zh")
    project.current_stage = 3
    project_repo = _InMemoryProjectRepo(project)
    stage_run_repo = _InMemoryStageRunRepo()

    from subflow.models.project import StageRun, StageRunStatus

    stage_run_repo.stage_runs[(project.id, StageName.ASR.value)] = StageRun(
        stage=StageName.ASR, status=StageRunStatus.FAILED
    )
    stage_run_repo.stage_runs[(project.id, StageName.LLM.value)] = StageRun(
        stage=StageName.LLM, status=StageRunStatus.COMPLETED
    )

    class _SpyRepo(_NoopRepo):
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def delete_by_project(self, project_id: str) -> None:  # noqa: ARG002
            self.calls.append("delete_by_project")

        async def clear_corrected_texts(self, project_id: str) -> None:  # noqa: ARG002
            self.calls.append("clear_corrected_texts")

        async def delete(self, project_id: str) -> None:  # noqa: ARG002
            self.calls.append("delete")

    vad_repo = _SpyRepo()
    asr_repo = _SpyRepo()
    asr_merged_repo = _SpyRepo()
    global_ctx_repo = _SpyRepo()
    semantic_repo = _SpyRepo()

    orch = PipelineOrchestrator(
        settings,
        store,
        project_repo=project_repo,
        stage_run_repo=stage_run_repo,
        vad_repo=vad_repo,
        asr_repo=asr_repo,
        asr_merged_chunk_repo=asr_merged_repo,
        global_context_repo=global_ctx_repo,
        semantic_chunk_repo=semantic_repo,
    )

    fake_runners = {StageName.ASR: _Runner(stage=StageName.ASR)}
    monkeypatch.setattr("subflow.pipeline.orchestrator.RUNNERS", fake_runners, raising=False)

    out_project, _ = await orch.run_stage(project, StageName.ASR)
    assert out_project.current_stage == 3
    assert out_project.status == ProjectStatus.PROCESSING

    assert "delete_by_project" not in vad_repo.calls
    assert "delete_by_project" in asr_repo.calls
    assert "delete_by_project" in asr_merged_repo.calls
    assert "delete_by_project" in global_ctx_repo.calls
    assert "delete_by_project" in semantic_repo.calls
    assert "clear_corrected_texts" in asr_repo.calls

    sr_asr = stage_run_repo.stage_runs[(project.id, StageName.ASR.value)]
    assert isinstance(sr_asr, StageRun)
    assert sr_asr.status == StageRunStatus.COMPLETED

    sr_llm = stage_run_repo.stage_runs[(project.id, StageName.LLM.value)]
    assert isinstance(sr_llm, StageRun)
    assert sr_llm.status == StageRunStatus.PENDING
