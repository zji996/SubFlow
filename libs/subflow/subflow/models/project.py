"""Project model (pipeline execution unit)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from subflow.models.subtitle_export import SubtitleExport


class ProjectStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class StageName(str, Enum):
    AUDIO_PREPROCESS = "audio_preprocess"
    VAD = "vad"
    ASR = "asr"
    LLM_ASR_CORRECTION = "llm_asr_correction"
    LLM = "llm"
    EXPORT = "export"


class StageRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _dt_to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _dt_from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass
class StageRun:
    stage: StageName
    status: StageRunStatus = StageRunStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    progress: int | None = None
    progress_message: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    error: str | None = None
    input_artifacts: dict[str, str] = field(default_factory=dict)
    output_artifacts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "status": self.status.value,
            "started_at": _dt_to_iso(self.started_at),
            "completed_at": _dt_to_iso(self.completed_at),
            "duration_ms": self.duration_ms,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "metrics": dict(self.metrics) or None,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "error": self.error,
            "input_artifacts": dict(self.input_artifacts),
            "output_artifacts": dict(self.output_artifacts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageRun":
        started_at = _dt_from_iso(data.get("started_at"))
        completed_at = _dt_from_iso(data.get("completed_at"))
        duration_ms = data.get("duration_ms")
        if duration_ms is None and started_at is not None and completed_at is not None:
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        metrics_raw = data.get("metrics")
        metrics = dict(metrics_raw) if isinstance(metrics_raw, dict) else {}
        return cls(
            stage=StageName(str(data.get("stage", StageName.AUDIO_PREPROCESS.value))),
            status=StageRunStatus(str(data.get("status", StageRunStatus.PENDING.value))),
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=int(duration_ms) if isinstance(duration_ms, int) else None,
            progress=int(data["progress"]) if isinstance(data.get("progress"), int) else None,
            progress_message=data.get("progress_message"),
            metrics=metrics,
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
            error=data.get("error"),
            input_artifacts=dict(data.get("input_artifacts") or {}),
            output_artifacts=dict(data.get("output_artifacts") or {}),
        )


@dataclass
class Project:
    id: str
    name: str
    media_url: str
    media_files: dict[str, Any] = field(default_factory=dict)
    source_language: str | None = None
    target_language: str = "zh"
    auto_workflow: bool = True
    status: ProjectStatus = ProjectStatus.PENDING
    current_stage: int = 0
    artifacts: dict[str, Any] = field(default_factory=dict)
    stage_runs: list[StageRun] = field(default_factory=list)
    exports: list[SubtitleExport] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def touch(self) -> None:
        self.updated_at = _utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "media_url": self.media_url,
            "media_files": dict(self.media_files or {}),
            "source_language": self.source_language,
            "target_language": self.target_language,
            "auto_workflow": bool(self.auto_workflow),
            "status": self.status.value,
            "current_stage": int(self.current_stage),
            "artifacts": dict(self.artifacts),
            "stage_runs": [sr.to_dict() for sr in self.stage_runs],
            "exports": [e.to_dict() for e in list(self.exports or [])],
            "created_at": _dt_to_iso(self.created_at),
            "updated_at": _dt_to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        stage_runs_raw = list(data.get("stage_runs") or [])
        exports_raw = list(data.get("exports") or [])
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            media_url=str(data.get("media_url", "")),
            media_files=dict(data.get("media_files") or {}),
            source_language=data.get("source_language"),
            target_language=str(data.get("target_language") or "zh"),
            auto_workflow=bool(data.get("auto_workflow", True)),
            status=ProjectStatus(str(data.get("status") or ProjectStatus.PENDING.value)),
            current_stage=int(data.get("current_stage") or 0),
            artifacts=dict(data.get("artifacts") or {}),
            stage_runs=[
                StageRun.from_dict(x) for x in stage_runs_raw if isinstance(x, dict)
            ],
            exports=[
                SubtitleExport.from_dict(x) for x in exports_raw if isinstance(x, dict)
            ],
            created_at=_dt_from_iso(data.get("created_at")) or _utcnow(),
            updated_at=_dt_from_iso(data.get("updated_at")) or _utcnow(),
        )
