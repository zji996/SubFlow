"""Build subtitle entries and export to multiple formats."""

from __future__ import annotations

from dataclasses import replace

from subflow.export.formatters.ass import ASSFormatter
from subflow.export.formatters.json_format import JSONFormatter
from subflow.export.formatters.srt import SRTFormatter
from subflow.export.formatters.vtt import VTTFormatter
from subflow.models.segment import ASRCorrectedSegment, ASRSegment, SemanticChunk
from subflow.models.subtitle_types import SubtitleEntry, SubtitleExportConfig, SubtitleFormat


class SubtitleExporter:
    def build_entries(
        self,
        chunks: list[SemanticChunk],
        asr_segments: list[ASRSegment],
        asr_corrected_segments: dict[int, ASRCorrectedSegment] | None,
    ) -> list[SubtitleEntry]:
        corrected_index: dict[int, ASRCorrectedSegment] = dict(asr_corrected_segments or {})

        chunk_by_segment_id: dict[int, SemanticChunk] = {}
        for semantic_chunk in chunks:
            for seg_id in list(semantic_chunk.asr_segment_ids or []):
                if seg_id not in chunk_by_segment_id:
                    chunk_by_segment_id[int(seg_id)] = semantic_chunk

        items: list[tuple[float, float, int, SubtitleEntry]] = []
        seq = 0

        for seg in asr_segments:
            corrected = corrected_index.get(seg.id)
            chunk_for_seg = chunk_by_segment_id.get(seg.id)
            primary = (chunk_for_seg.translation if chunk_for_seg is not None else "") or ""
            primary = primary.strip()
            secondary = ((corrected.text if corrected is not None else "") or "").strip() or (
                (seg.text or "").strip()
            )
            if not primary and not secondary:
                continue
            start, end = float(seg.start), float(seg.end)
            entry = SubtitleEntry(
                index=0,
                start=start,
                end=end,
                primary_text=primary,
                secondary_text=secondary,
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
        if config.content.value not in {"both", "primary_only", "secondary_only"}:
            raise ValueError("content must be 'both', 'primary_only', or 'secondary_only'")

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
