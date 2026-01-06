"""Build subtitle entries and export to multiple formats."""

from __future__ import annotations

from dataclasses import replace

from subflow.export.formatters.ass import ASSFormatter
from subflow.export.formatters.json_format import JSONFormatter
from subflow.export.formatters.srt import SRTFormatter
from subflow.export.formatters.vtt import VTTFormatter
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk
from subflow.models.subtitle_types import SubtitleEntry, SubtitleExportConfig, SubtitleFormat


def _join_segment_texts(parts: list[str]) -> str:
    out = ""
    for part in parts:
        t = (part or "").strip()
        if not t:
            continue
        if out:
            prev = out[-1]
            nxt = t[0]
            if (
                prev.isascii()
                and prev.isalnum()
                and nxt.isascii()
                and nxt.isalnum()
                and not out.endswith(" ")
            ):
                out += " "
        out += t
    return out


class SubtitleExporter:
    def build_entries(
        self,
        chunks: list[SemanticChunk],
        asr_segments: list[ASRSegment],
        asr_corrected_segments: dict[int, ASRCorrectedSegment] | None,
    ) -> list[SubtitleEntry]:
        asr_index: dict[int, ASRSegment] = {seg.id: seg for seg in asr_segments}
        corrected_index: dict[int, ASRCorrectedSegment] = dict(asr_corrected_segments or {})

        used_segment_ids: set[int] = set()
        items: list[tuple[float, float, int, SubtitleEntry]] = []
        seq = 0

        def _segment_text(seg_id: int) -> str:
            corrected = corrected_index.get(seg_id)
            if corrected is not None and (corrected.text or "").strip():
                return corrected.text
            seg = asr_index.get(seg_id)
            return (seg.text if seg is not None else "") or ""

        def _segment_time(seg_id: int) -> tuple[float, float]:
            seg = asr_index.get(seg_id)
            if seg is None:
                return 0.0, 0.0
            return float(seg.start), float(seg.end)

        for chunk in chunks:
            ids = sorted(list(chunk.asr_segment_ids or []))
            if not ids:
                continue
            used_segment_ids |= set(ids)
            start, _ = _segment_time(ids[0])
            _, end = _segment_time(ids[-1])
            secondary = _join_segment_texts([_segment_text(i) for i in ids])
            primary = (chunk.translation or "").strip()
            entry = SubtitleEntry(
                index=0,
                start=start,
                end=end,
                primary_text=primary,
                secondary_text=secondary,
            )
            items.append((start, end, seq, entry))
            seq += 1

        for seg in asr_segments:
            corrected = corrected_index.get(seg.id)
            is_filler = bool(corrected.is_filler) if corrected is not None else False
            if not is_filler:
                continue
            if seg.id in used_segment_ids:
                continue
            start, end = float(seg.start), float(seg.end)
            entry = SubtitleEntry(
                index=0,
                start=start,
                end=end,
                primary_text="",
                secondary_text=_segment_text(seg.id),
            )
            items.append((start, end, seq, entry))
            seq += 1

        for seg in asr_segments:
            if seg.id in used_segment_ids:
                continue
            corrected = corrected_index.get(seg.id)
            if corrected is not None and corrected.is_filler:
                continue
            if not (seg.text or "").strip():
                continue
            start, end = float(seg.start), float(seg.end)
            entry = SubtitleEntry(
                index=0,
                start=start,
                end=end,
                primary_text="",
                secondary_text=_segment_text(seg.id),
            )
            items.append((start, end, seq, entry))
            seq += 1

        items.sort(key=lambda x: (x[0], x[1], x[2]))

        entries: list[SubtitleEntry] = []
        for i, (_, __, ___, entry) in enumerate(items, start=1):
            entries.append(replace(entry, index=i))
        return entries

    def export(
        self,
        chunks: list[SemanticChunk],
        asr_segments: list[ASRSegment],
        asr_corrected_segments: dict[int, ASRCorrectedSegment] | None,
        config: SubtitleExportConfig,
    ) -> str:
        entries = self.build_entries(
            chunks=chunks,
            asr_segments=asr_segments,
            asr_corrected_segments=asr_corrected_segments,
        )

        if config.primary_position not in {"top", "bottom"}:
            raise ValueError("primary_position must be 'top' or 'bottom'")

        match config.format:
            case SubtitleFormat.SRT:
                return SRTFormatter().format(entries, config)
            case SubtitleFormat.VTT:
                return VTTFormatter().format(entries, config)
            case SubtitleFormat.ASS:
                return ASSFormatter().format(entries, config)
            case SubtitleFormat.JSON:
                return JSONFormatter().format(entries, config)
            case _:
                raise ValueError(f"Unknown subtitle format: {config.format}")
