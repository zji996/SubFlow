from __future__ import annotations

from datetime import datetime, timedelta, timezone

from subflow.models.project import Project, ProjectStatus, StageName, StageRun, StageRunStatus
from subflow.models.subtitle_export import SubtitleExport, SubtitleExportSource
from subflow.models.subtitle_types import SubtitleContent, SubtitleFormat


def test_stage_run_roundtrip_and_duration_autofill() -> None:
    started = datetime.now(tz=timezone.utc) - timedelta(seconds=2)
    completed = datetime.now(tz=timezone.utc)
    run = StageRun(
        stage=StageName.ASR,
        status=StageRunStatus.COMPLETED,
        started_at=started,
        completed_at=completed,
        duration_ms=None,
        progress=100,
        progress_message="completed",
        input_artifacts={"in.json": "key1"},
        output_artifacts={"out.json": "key2"},
    )
    data = run.to_dict()
    assert data["duration_ms"] is None

    restored = StageRun.from_dict(data)
    assert restored.stage == StageName.ASR
    assert restored.status == StageRunStatus.COMPLETED
    assert restored.duration_ms is not None
    assert restored.duration_ms >= 0
    assert restored.progress == 100
    assert restored.output_artifacts["out.json"] == "key2"


def test_project_roundtrip_includes_exports() -> None:
    now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    exp = SubtitleExport(
        id="export_1",
        project_id="proj_1",
        created_at=now,
        format=SubtitleFormat.SRT,
        content_mode=SubtitleContent.BOTH,
        config_json="{}",
        storage_stage="exports",
        storage_name="export_1.srt",
        storage_key="mem://exports/export_1.srt",
        source=SubtitleExportSource.AUTO,
    )
    project = Project(
        id="proj_1",
        name="demo",
        media_url="https://example.com/video.mp4",
        source_language="en",
        target_language="zh",
        auto_workflow=True,
        status=ProjectStatus.PROCESSING,
        current_stage=3,
        artifacts={"asr": {"asr_segments.json": "k"}},
        stage_runs=[StageRun(stage=StageName.ASR, status=StageRunStatus.RUNNING)],
        exports=[exp],
        created_at=now,
        updated_at=now,
    )
    restored = Project.from_dict(project.to_dict())
    assert restored.id == "proj_1"
    assert restored.status == ProjectStatus.PROCESSING
    assert restored.current_stage == 3
    assert len(restored.stage_runs) == 1
    assert len(restored.exports) == 1
    assert restored.exports[0].id == "export_1"
    assert restored.exports[0].format == SubtitleFormat.SRT
