"""JSON subtitle formatter."""

from __future__ import annotations

import json

from subflow.export.formatters.base import SubtitleFormatter
from subflow.models.subtitle_types import SubtitleEntry, SubtitleExportConfig


class JSONFormatter(SubtitleFormatter):
    def format(self, entries: list[SubtitleEntry], config: SubtitleExportConfig) -> str:
        data = {
            "version": "1.0",
            "include_secondary": config.include_secondary,
            "primary_position": config.primary_position,
            "entries": [
                {
                    "index": e.index,
                    "start": e.start,
                    "end": e.end,
                    "primary_text": e.primary_text,
                    "secondary_text": e.secondary_text,
                }
                for e in entries
                if (e.primary_text or "").strip() or (e.secondary_text or "").strip()
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

