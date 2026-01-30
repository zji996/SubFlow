"""Audit NeMo VAD parameters on a reference audio.

Usage:
  uv run --project apps/worker scripts/audit_vad_params.py

Default input:
  assets/test_video/vocals.wav
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from subflow.config import Settings
from subflow.models.segment import VADSegment
from subflow.providers import get_vad_provider


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit VAD params (regions + frame probs stats)")
    p.add_argument(
        "--audio",
        default="assets/test_video/vocals.wav",
        help="Input audio path (16kHz mono recommended)",
    )
    p.add_argument(
        "--json-out",
        default=None,
        help="Optional JSON output path",
    )
    p.add_argument(
        "--top",
        type=int,
        default=10,
        help="Print top-N longest regions and gaps",
    )
    return p.parse_args()


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    p = float(min(max(p, 0.0), 100.0))
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_values[int(k)])
    d0 = sorted_values[int(f)] * (c - k)
    d1 = sorted_values[int(c)] * (k - f)
    return float(d0 + d1)


def _summarize(values: list[float]) -> dict[str, float]:
    v = sorted(float(x) for x in values if x is not None)
    if not v:
        return {
            "count": 0.0,
            "min": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "max": 0.0,
            "mean": 0.0,
        }
    mean = sum(v) / float(len(v))
    return {
        "count": float(len(v)),
        "min": float(v[0]),
        "p50": _percentile(v, 50.0),
        "p90": _percentile(v, 90.0),
        "p95": _percentile(v, 95.0),
        "max": float(v[-1]),
        "mean": float(mean),
    }


def main() -> int:
    args = _parse_args()
    settings = Settings()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        raise SystemExit(f"Audio not found: {audio_path}")

    vad_provider = get_vad_provider(settings.vad.model_dump())
    detect_with_probs = getattr(vad_provider, "detect_with_probs", None)
    if not callable(detect_with_probs):
        raise SystemExit("VAD provider does not support detect_with_probs()")

    print("[1/3] VAD config", flush=True)
    print(
        json.dumps(
            {
                "provider": settings.vad.provider,
                "threshold": settings.vad.threshold,
                "min_silence_duration_ms": settings.vad.min_silence_duration_ms,
                "min_speech_duration_ms": settings.vad.min_speech_duration_ms,
                "target_max_segment_s": settings.vad.target_max_segment_s,
                "split_threshold": settings.vad.split_threshold,
                "split_search_backtrack_ratio": settings.vad.split_search_backtrack_ratio,
                "split_search_forward_ratio": settings.vad.split_search_forward_ratio,
                "split_gap_s": settings.vad.split_gap_s,
                "nemo_device": settings.vad.nemo_device,
                "nemo_model_path": str(settings.vad.nemo_model_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )

    print(f"[2/3] detect_with_probs: {audio_path}", flush=True)
    timestamps, frame_probs = detect_with_probs(str(audio_path))

    # Prefer coarse regions (after merge + min_speech filtering).
    regions = getattr(vad_provider, "last_regions", None)
    vad_regions = (
        [VADSegment(start=float(s), end=float(e)) for s, e in regions]
        if isinstance(regions, list) and regions
        else [VADSegment(start=float(s), end=float(e)) for s, e in timestamps]
    )
    vad_regions.sort(key=lambda r: (float(r.start), float(r.end)))

    durations = [float(r.end) - float(r.start) for r in vad_regions if float(r.end) > float(r.start)]
    gaps: list[float] = []
    for a, b in zip(vad_regions, vad_regions[1:], strict=False):
        g = float(b.start) - float(a.end)
        if g > 0:
            gaps.append(float(g))

    print("[3/3] stats", flush=True)
    duration_stats = _summarize(durations)
    gap_stats = _summarize(gaps)

    out: dict[str, object] = {
        "audio": str(audio_path),
        "regions_count": len(vad_regions),
        "regions_duration_s": duration_stats,
        "gaps_s": gap_stats,
        "frame_probs_count": int(getattr(frame_probs, "numel", lambda: len(frame_probs))()),
        "frame_hop_s": float(getattr(vad_provider, "frame_hop_s", 0.02)),
    }

    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)

    top = max(0, int(args.top))
    if top > 0:
        longest_regions = sorted(
            [(i, float(r.start), float(r.end), float(r.end) - float(r.start)) for i, r in enumerate(vad_regions)],
            key=lambda t: t[3],
            reverse=True,
        )[:top]
        longest_gaps = sorted(
            [(i, float(g)) for i, g in enumerate(gaps)],
            key=lambda t: t[1],
            reverse=True,
        )[:top]
        print("\nTop regions (id, start, end, dur_s):", flush=True)
        for rid, s, e, d in longest_regions:
            print(f"  - {rid:04d} {s:8.2f} {e:8.2f}  dur={d:6.2f}s", flush=True)
        print("\nTop gaps (index, gap_s):", flush=True)
        for i, g in longest_gaps:
            print(f"  - {i:04d} gap={g:6.2f}s", flush=True)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote: {out_path}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

