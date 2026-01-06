from __future__ import annotations

import torch

from subflow.providers.vad.nemo_marblenet import NemoMarbleNetVADProvider


def test_nemo_vad_valley_split_creates_gap() -> None:
    # 20ms hop, 20s duration
    hop = 0.02
    duration_s = 20.0
    frames = int(duration_s / hop)

    # One long "speech" region with a clear silence valley around 8s.
    probs = torch.full((frames,), 0.9, dtype=torch.float32)
    valley_start = int(8.0 / hop)
    valley_end = int(8.3 / hop)  # 300ms valley
    probs[valley_start:valley_end] = 0.0

    provider = NemoMarbleNetVADProvider(
        model_path="noop.nemo",
        threshold=0.5,
        min_silence_duration_ms=80,
        min_speech_duration_ms=200,
        target_max_segment_s=7.0,
        split_search_backtrack_ratio=0.5,
        split_search_forward_ratio=0.05,
        frame_hop_s=hop,
        device="cpu",
    )

    segs = provider._postprocess(probs, duration_s)  # type: ignore[attr-defined]
    assert len(segs) >= 2

    gaps = [segs[i + 1][0] - segs[i][1] for i in range(len(segs) - 1)]
    assert max(gaps) >= 0.2


def test_nemo_vad_split_gap_s_creates_micro_gap_without_valley() -> None:
    hop = 0.02
    duration_s = 20.0
    frames = int(duration_s / hop)

    # Continuous high-prob speech => no natural valley.
    probs = torch.full((frames,), 0.9, dtype=torch.float32)

    provider = NemoMarbleNetVADProvider(
        model_path="noop.nemo",
        threshold=0.5,
        min_silence_duration_ms=60,
        min_speech_duration_ms=160,
        target_max_segment_s=7.0,
        split_search_backtrack_ratio=0.5,
        split_search_forward_ratio=0.05,
        split_gap_s=0.08,
        frame_hop_s=hop,
        device="cpu",
    )

    segs = provider._postprocess(probs, duration_s)  # type: ignore[attr-defined]
    assert len(segs) >= 2

    gaps = [segs[i + 1][0] - segs[i][1] for i in range(len(segs) - 1)]
    assert max(gaps) >= 0.06
