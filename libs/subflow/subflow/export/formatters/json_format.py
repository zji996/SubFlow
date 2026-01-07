"""JSON subtitle formatter."""

from __future__ import annotations

import json

from subflow.export.formatters.base import SubtitleFormatter, selected_lines
from subflow.models.subtitle_types import SubtitleEntry, SubtitleExportConfig


class JSONFormatter(SubtitleFormatter):
    def format(self, entries: list[SubtitleEntry], config: SubtitleExportConfig) -> str:
        rendered: list[dict[str, object]] = []
        for entry in entries:
            lines = selected_lines(entry.primary_text, entry.secondary_text, config)
            if not lines:
                continue
            primary_text = ""
            secondary_text = ""
            for kind, text in lines:
                if kind == "primary":
                    primary_text = text
                elif kind == "secondary":
                    secondary_text = text
            rendered.append(
                {
                    "index": entry.index,
                    "start": entry.start,
                    "end": entry.end,
                    "primary_text": primary_text,
                    "secondary_text": secondary_text,
                }
            )

        data = {
            "version": "1.0",
            "content": config.content.value,
            "primary_position": config.primary_position,
            "entries": rendered,
        }
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
