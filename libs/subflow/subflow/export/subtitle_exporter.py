"""Build subtitle entries and export to multiple formats."""

from __future__ import annotations

from dataclasses import replace

from subflow.export.formatters.ass import ASSFormatter
from subflow.export.formatters.json_format import JSONFormatter
from subflow.export.formatters.srt import SRTFormatter
from subflow.export.formatters.vtt import VTTFormatter
from subflow.models.segment import (
    ASRCorrectedSegment,
    ASRSegment,
    SegmentTranslation,
    SemanticChunk,
    TranslationChunk,
)
from subflow.models.subtitle_types import (
    SubtitleEntry,
    SubtitleExportConfig,
    SubtitleFormat,
)


class SubtitleExporter:
    def export_entries(self, entries: list[SubtitleEntry], config: SubtitleExportConfig) -> str:
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

    def build_entries(
        self,
        chunks: list[SemanticChunk],
        asr_segments: list[ASRSegment],
        asr_corrected_segments: dict[int, ASRCorrectedSegment] | None,
        segment_translations: list[SegmentTranslation] | None = None,
    ) -> list[SubtitleEntry]:
        corrected_index: dict[int, ASRCorrectedSegment] = dict(asr_corrected_segments or {})

        ordered_segments = sorted(
            asr_segments, key=lambda s: (float(s.start), float(s.end), int(s.id))
        )

        translation_by_segment_id: dict[int, str] = {}

        # Preferred: direct 1:1 translations from Stage 5.
        if segment_translations:
            for tr in list(segment_translations or []):
                sid = int(tr.segment_id)
                if sid not in translation_by_segment_id:
                    translation_by_segment_id[sid] = str(tr.translation or "")

        # Backward compatibility: derive per-segment translation from legacy semantic_chunks.
        if not translation_by_segment_id:
            for semantic_chunk in list(chunks or []):
                for ch in list(semantic_chunk.translation_chunks or []):
                    if not isinstance(ch, TranslationChunk):
                        continue
                    seg_id = int(ch.segment_id)
                    if seg_id not in translation_by_segment_id:
                        translation_by_segment_id[seg_id] = str(ch.text or "")
            for semantic_chunk in list(chunks or []):
                chunk_text = str(semantic_chunk.translation or "")
                if not chunk_text:
                    continue
                for seg_id in list(semantic_chunk.asr_segment_ids or []):
                    sid = int(seg_id)
                    if sid not in translation_by_segment_id:
                        translation_by_segment_id[sid] = chunk_text

        items: list[tuple[float, float, int, SubtitleEntry]] = []
        seq = 0

        for seg in ordered_segments:
            corrected = corrected_index.get(seg.id)
            primary = str(translation_by_segment_id.get(int(seg.id), "") or "").strip()
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
        *,
        segment_translations: list[SegmentTranslation] | None = None,
    ) -> str:
        entries = self.build_entries(
            chunks=chunks,
            asr_segments=asr_segments,
            asr_corrected_segments=asr_corrected_segments,
            segment_translations=segment_translations,
        )
        return self.export_entries(entries, config)
