"""Subtitle export metadata persisted on a project."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from subflow.models.subtitle_types import SubtitleContent, SubtitleFormat


class SubtitleExportSource(str, Enum):
    AUTO = "auto"
    EDITED = "edited"


def _dt_to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _dt_from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass
class SubtitleExport:
    id: str
    project_id: str
    created_at: datetime
    format: SubtitleFormat
    content_mode: SubtitleContent
    config_json: str
    storage_stage: str
    storage_name: str
    storage_key: str
    source: SubtitleExportSource = SubtitleExportSource.AUTO
    entries_name: str | None = None
    entries_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "created_at": _dt_to_iso(self.created_at),
            "format": self.format.value,
            "content_mode": self.content_mode.value,
            "config_json": self.config_json,
            "storage_stage": self.storage_stage,
            "storage_name": self.storage_name,
            "storage_key": self.storage_key,
            "source": self.source.value,
            "entries_name": self.entries_name,
            "entries_key": self.entries_key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubtitleExport":
        created_at = _dt_from_iso(data.get("created_at")) or datetime.now(tz=timezone.utc)
        fmt = SubtitleFormat(str(data.get("format") or SubtitleFormat.SRT.value))
        content_mode = SubtitleContent(str(data.get("content_mode") or SubtitleContent.BOTH.value))
        return cls(
            id=str(data.get("id") or ""),
            project_id=str(data.get("project_id") or ""),
            created_at=created_at,
            format=fmt,
            content_mode=content_mode,
            config_json=str(data.get("config_json") or "{}"),
            storage_stage=str(data.get("storage_stage") or "exports"),
            storage_name=str(data.get("storage_name") or ""),
            storage_key=str(data.get("storage_key") or ""),
            source=SubtitleExportSource(str(data.get("source") or SubtitleExportSource.AUTO.value)),
            entries_name=data.get("entries_name"),
            entries_key=data.get("entries_key"),
        )
