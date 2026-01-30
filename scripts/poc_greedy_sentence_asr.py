"""Greedy Sentence-Aligned ASR PoC.

Usage:
  `uv run --project apps/worker scripts/poc_greedy_sentence_asr.py`

Input:
  - `assets/test_video/vocals.wav` (already separated vocals, 16kHz mono recommended)

Output (default: `data/poc_greedy_sentence_asr/`):
  - `vad_regions.json`
  - `vad_frame_probs.pt`
  - `sentence_segments.json`
  - `output.srt`
  - `asr_segments.json`
  - `asr_merged_chunks.json`
  - `asr_corrected_segments.json`
  - `output_corrected.srt`

GPU:
  - Defaults to using GPU1 by setting `CUDA_VISIBLE_DEVICES=1` if not already set.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1")

from subflow.config import Settings
from subflow.export.formatters.base import SubtitleFormatter
from subflow.models.segment import ASRSegment as ModelASRSegment
from subflow.models.segment import ASRMergedChunk, VADSegment
from subflow.providers import get_asr_provider, get_vad_provider
from subflow.stages.llm_asr_correction import LLMASRCorrectionStage
from subflow.utils.audio import cut_audio_segment
from subflow.utils.greedy_sentence_aligner import (
    GreedySentenceAlignerConfig,
    SentenceAlignedSegment,
    estimate_text_units,
    greedy_sentence_align_region,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Greedy Sentence-Aligned ASR PoC")
    parser.add_argument(
        "--input-audio",
        default="assets/test_video/vocals.wav",
        help="Input vocals wav path (16kHz mono recommended)",
    )
    parser.add_argument(
        "--duration-s",
        type=float,
        default=None,
        help="Only process first N seconds (default: full audio)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (defaults to data/poc_greedy_sentence_asr)",
    )
    parser.add_argument("--max-chunk-s", type=float, default=10.0, help="Max ASR window size")
    parser.add_argument(
        "--merged-max-chunk-s",
        type=float,
        default=15.0,
        help="Max merged chunk duration (Stage 4 context window)",
    )
    parser.add_argument(
        "--vad-search-range-s",
        type=float,
        default=1.0,
        help="VAD valley search range (± seconds)",
    )
    parser.add_argument(
        "--vad-valley-threshold",
        type=float,
        default=0.3,
        help="Prob below this treated as silence",
    )
    parser.add_argument(
        "--max-segment-s",
        type=float,
        default=8.0,
        help="Hard upper bound for segments without clear punctuation",
    )
    parser.add_argument(
        "--max-segment-chars",
        type=int,
        default=50,
        help="Comma split threshold (CJK chars + Latin words)",
    )
    parser.add_argument("--min-segment-s", type=float, default=0.5, help="Minimum segment length")
    parser.add_argument("--keep-chunks", action="store_true", help="Keep cut chunks for debugging")
    parser.add_argument("--skip-llm", action="store_true", help="Skip Stage 4 LLM correction")
    return parser.parse_args()


def _segments_to_srt(segments: list[SentenceAlignedSegment]) -> str:
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(
            f"{SubtitleFormatter.seconds_to_timestamp(float(seg.start), ',')} --> "
            f"{SubtitleFormatter.seconds_to_timestamp(float(seg.end), ',')}"
        )
        lines.append((seg.text or "").strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _asr_segments_to_srt(segments: list[ModelASRSegment]) -> str:
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(
            f"{SubtitleFormatter.seconds_to_timestamp(float(seg.start), ',')} --> "
            f"{SubtitleFormatter.seconds_to_timestamp(float(seg.end), ',')}"
        )
        lines.append((seg.text or "").strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_merged_chunks(
    *,
    asr_segments: list[ModelASRSegment],
    segment_region_ids: list[int],
    max_chunk_s: float,
) -> list[ASRMergedChunk]:
    if len(asr_segments) != len(segment_region_ids):
        raise ValueError("asr_segments and segment_region_ids length mismatch")

    chunks: list[ASRMergedChunk] = []
    next_chunk_id_by_region: dict[int, int] = {}

    cur: ASRMergedChunk | None = None
    for seg, region_id in zip(asr_segments, segment_region_ids, strict=True):
        if cur is None:
            chunk_id = next_chunk_id_by_region.get(int(region_id), 0)
            next_chunk_id_by_region[int(region_id)] = chunk_id + 1
            cur = ASRMergedChunk(
                region_id=int(region_id),
                chunk_id=int(chunk_id),
                start=float(seg.start),
                end=float(seg.end),
                segment_ids=[int(seg.id)],
                text="",
            )
            continue

        new_region = int(region_id) != int(cur.region_id)
        new_duration = float(seg.end) - float(cur.start)
        if new_region or (new_duration > float(max_chunk_s)):
            chunks.append(cur)
            chunk_id = next_chunk_id_by_region.get(int(region_id), 0)
            next_chunk_id_by_region[int(region_id)] = chunk_id + 1
            cur = ASRMergedChunk(
                region_id=int(region_id),
                chunk_id=int(chunk_id),
                start=float(seg.start),
                end=float(seg.end),
                segment_ids=[int(seg.id)],
                text="",
            )
            continue

        cur.end = float(seg.end)
        cur.segment_ids.append(int(seg.id))

    if cur is not None:
        chunks.append(cur)

    return chunks


async def _run() -> int:
    args = _parse_args()
    settings = Settings()

    input_audio = Path(args.input_audio)
    if not input_audio.exists():
        raise SystemExit(f"Input audio not found: {input_audio}")

    # Keep PoC deterministic: use coarse VAD regions (no VAD-aware splitting).
    settings.vad.target_max_segment_s = None

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(settings.data_dir) / "poc_greedy_sentence_asr"
    output_dir.mkdir(parents=True, exist_ok=True)

    asr_provider = get_asr_provider(settings.asr.model_dump())
    vad_provider = get_vad_provider(settings.vad.model_dump())

    ffmpeg_bin = str(getattr(settings.audio, "ffmpeg_bin", "ffmpeg"))
    tmp_audio_path: Path | None = None

    if args.duration_s is not None and float(args.duration_s) > 0:
        tmp_audio_path = output_dir / ".tmp_input_trimmed.wav"
        print(f"[1/6] trim audio: {input_audio} -> {tmp_audio_path}", flush=True)
        await cut_audio_segment(
            input_path=str(input_audio),
            output_path=str(tmp_audio_path),
            start=0.0,
            end=float(args.duration_s),
            ffmpeg_bin=ffmpeg_bin,
        )
        vocals_path = str(tmp_audio_path)
    else:
        print(f"[1/6] input audio: {input_audio}", flush=True)
        vocals_path = str(input_audio)

    if not hasattr(vad_provider, "detect_with_probs"):
        raise SystemExit("VAD provider does not support detect_with_probs()")

    print(f"[2/6] VAD detect_with_probs: {vocals_path}", flush=True)
    regions, frame_probs = vad_provider.detect_with_probs(vocals_path)  # type: ignore[attr-defined]
    regions_json = [{"start": float(s), "end": float(e)} for s, e in regions]
    (output_dir / "vad_regions.json").write_text(
        json.dumps(regions_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    import torch

    torch.save(frame_probs, str(output_dir / "vad_frame_probs.pt"))

    chunk_dir = output_dir / "chunks"
    if args.keep_chunks:
        chunk_dir.mkdir(parents=True, exist_ok=True)

    chunk_index = 0

    async def _transcribe_window(start: float, end: float) -> str:
        nonlocal chunk_index
        chunk_index += 1

        if args.keep_chunks:
            chunk_path = chunk_dir / f"chunk_{chunk_index:05d}_{start:.2f}_{end:.2f}.wav"
        else:
            chunk_path = output_dir / f".tmp_chunk_{chunk_index:05d}.wav"

        await cut_audio_segment(
            input_path=vocals_path,
            output_path=str(chunk_path),
            start=float(start),
            end=float(end),
            ffmpeg_bin=ffmpeg_bin,
        )
        try:
            text = await asr_provider.transcribe_segment(str(chunk_path), float(start), float(end))
            return text.strip()
        finally:
            if (not args.keep_chunks) and chunk_path.exists():
                try:
                    os.remove(chunk_path)
                except OSError:
                    pass

    frame_hop_s = float(getattr(vad_provider, "frame_hop_s", 0.02))
    cfg = GreedySentenceAlignerConfig(
        max_chunk_s=float(args.max_chunk_s),
        max_segment_s=float(args.max_segment_s),
        max_segment_chars=int(args.max_segment_chars),
        vad_search_range_s=float(args.vad_search_range_s),
        vad_valley_threshold=float(args.vad_valley_threshold),
        min_segment_s=float(args.min_segment_s),
    )

    print(f"[3/6] greedy align (regions={len(regions)})", flush=True)
    sentence_segments: list[SentenceAlignedSegment] = []
    sentence_segment_region_ids: list[int] = []
    for region_id, (region_start, region_end) in enumerate(regions):
        segs = await greedy_sentence_align_region(
            _transcribe_window,
            frame_probs=frame_probs,
            frame_hop_s=frame_hop_s,
            region_start=float(region_start),
            region_end=float(region_end),
            config=cfg,
        )
        sentence_segments.extend(segs)
        sentence_segment_region_ids.extend([int(region_id)] * len(segs))

    endings_sentence = set(str(cfg.sentence_endings))
    endings_clause = set(str(cfg.clause_endings))
    print("\nSegment stats (idx start end dur_s units comma_split):", flush=True)
    for i, seg in enumerate(sentence_segments):
        txt = (seg.text or "").strip()
        comma_split = bool(txt) and (txt[-1] in endings_clause) and (txt[-1] not in endings_sentence)
        units = estimate_text_units(txt)
        dur = float(seg.end) - float(seg.start)
        print(
            f"  - {i:04d} {float(seg.start):8.2f} {float(seg.end):8.2f}  dur={dur:6.2f}s  "
            f"units={units:3d}  comma_split={'y' if comma_split else 'n'}",
            flush=True,
        )

    (output_dir / "sentence_segments.json").write_text(
        json.dumps([asdict(s) for s in sentence_segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "output.srt").write_text(_segments_to_srt(sentence_segments), encoding="utf-8")

    print(f"[4/6] segmented ASR (segments={len(sentence_segments)})", flush=True)
    asr_segments: list[ModelASRSegment] = []
    for i, seg in enumerate(sentence_segments):
        text = await _transcribe_window(float(seg.start), float(seg.end))
        asr_segments.append(
            ModelASRSegment(
                id=int(i),
                start=float(seg.start),
                end=float(seg.end),
                text=str(text or "").strip(),
            )
        )

    (output_dir / "asr_segments.json").write_text(
        json.dumps([asdict(s) for s in asr_segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[5/6] merged ASR (max_chunk_s={float(args.merged_max_chunk_s):.2f})", flush=True)
    merged_chunks = _build_merged_chunks(
        asr_segments=asr_segments,
        segment_region_ids=sentence_segment_region_ids,
        max_chunk_s=float(args.merged_max_chunk_s),
    )
    for chunk in merged_chunks:
        chunk.text = await _transcribe_window(float(chunk.start), float(chunk.end))

    (output_dir / "asr_merged_chunks.json").write_text(
        json.dumps([asdict(c) for c in merged_chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.skip_llm:
        print("[6/6] skip llm correction", flush=True)
    else:
        print("[6/6] llm asr correction", flush=True)
        try:
            stage = LLMASRCorrectionStage(settings)
        except Exception as exc:
            print(f"  - llm stage init failed, skip correction: {exc}", flush=True)
        else:
            try:
                if not stage.api_key:
                    print("  - missing llm api_key, fallback (no correction)", flush=True)
                out_ctx = await stage.execute(
                    {
                        "asr_segments": asr_segments,
                        "asr_merged_chunks": merged_chunks,
                        "vad_regions": [
                            VADSegment(start=float(s), end=float(e), region_id=int(i))
                            for i, (s, e) in enumerate(regions)
                        ],
                    }
                )
                asr_segments = list(out_ctx.get("asr_segments") or asr_segments)
            finally:
                await stage.close()

    (output_dir / "asr_corrected_segments.json").write_text(
        json.dumps([asdict(s) for s in asr_segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "output_corrected.srt").write_text(_asr_segments_to_srt(asr_segments), encoding="utf-8")

    await asr_provider.close()
    await vad_provider.close()

    if tmp_audio_path is not None and tmp_audio_path.exists():
        try:
            tmp_audio_path.unlink()
        except OSError:
            pass

    print(f"done: {output_dir}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
