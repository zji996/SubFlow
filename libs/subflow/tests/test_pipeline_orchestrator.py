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


@dataclass(frozen=True)
class _Runner:
    stage: StageName
    fail: bool = False
    progress_steps: list[int] | None = None

    async def run(self, *, settings, store, project, ctx, progress_reporter=None):
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

    orch = PipelineOrchestrator(settings, store, on_project_update=on_update)
    project = Project(id="proj_1", name="demo", media_url="u", target_language="zh")

    fake_runners = {s: _Runner(stage=s, progress_steps=[10, 100]) for s in [StageName.AUDIO_PREPROCESS, StageName.VAD, StageName.ASR, StageName.LLM_ASR_CORRECTION, StageName.LLM]}
    monkeypatch.setattr("subflow.pipeline.orchestrator.RUNNERS", fake_runners, raising=False)

    out_project, ctx = await orch.run_stage(project, StageName.ASR)
    assert out_project.current_stage == 3
    assert out_project.status == ProjectStatus.PROCESSING
    assert len(out_project.stage_runs) == 3
    assert ctx["project_id"] == "proj_1"
    assert updates

    out_project, _ = await orch.run_stage(out_project, StageName.LLM)
    assert out_project.status == ProjectStatus.COMPLETED
    assert out_project.current_stage == 5


@pytest.mark.asyncio
async def test_orchestrator_error_sets_failed_status_and_error_code(settings, monkeypatch) -> None:
    store = InMemoryArtifactStore()
    orch = PipelineOrchestrator(settings, store)
    project = Project(id="proj_2", name="demo", media_url="u", target_language="zh")

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
