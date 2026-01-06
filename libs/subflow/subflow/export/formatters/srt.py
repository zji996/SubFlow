"""SRT subtitle formatter (dual-line)."""

from __future__ import annotations

from subflow.export.formatters.base import SubtitleFormatter
from subflow.models.subtitle_types import SubtitleEntry, SubtitleExportConfig


class SRTFormatter(SubtitleFormatter):
    def format(self, entries: list[SubtitleEntry], config: SubtitleExportConfig) -> str:
        lines: list[str] = []

        for entry in entries:
            primary = (entry.primary_text or "").strip()
            secondary = (entry.secondary_text or "").strip()
            if not primary and not secondary:
                continue

            lines.append(str(entry.index))
            lines.append(
                f"{self.seconds_to_timestamp(entry.start, ',')} --> "
                f"{self.seconds_to_timestamp(entry.end, ',')}"
            )

            include_secondary = config.include_secondary or (not primary and bool(secondary))
            if include_secondary:
                if config.primary_position == "top":
                    if primary:
                        lines.append(primary)
                    if secondary:
                        lines.append(secondary)
                else:
                    if secondary:
                        lines.append(secondary)
                    if primary:
                        lines.append(primary)
            else:
                if primary:
                    lines.append(primary)

            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

