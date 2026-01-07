"""SRT subtitle formatter (dual-line)."""

from __future__ import annotations

from subflow.export.formatters.base import SubtitleFormatter, selected_lines
from subflow.models.subtitle_types import SubtitleEntry, SubtitleExportConfig


class SRTFormatter(SubtitleFormatter):
    def format(self, entries: list[SubtitleEntry], config: SubtitleExportConfig) -> str:
        lines: list[str] = []

        for entry in entries:
            rendered = selected_lines(entry.primary_text, entry.secondary_text, config)
            if not rendered:
                continue

            lines.append(str(entry.index))
            lines.append(
                f"{self.seconds_to_timestamp(entry.start, ',')} --> "
                f"{self.seconds_to_timestamp(entry.end, ',')}"
            )

            for _kind, text in rendered:
                lines.append(text)

            lines.append("")

        return "\n".join(lines).rstrip() + "\n"
