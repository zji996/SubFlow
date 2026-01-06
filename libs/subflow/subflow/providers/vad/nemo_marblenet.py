"""NVIDIA NeMo Frame-VAD MarbleNet provider.

Model source (ModelScope):
  https://www.modelscope.cn/models/nv-community/Frame_VAD_Multilingual_MarbleNet_v2.0

This model is shipped as a NeMo `.nemo` checkpoint, so inference requires `nemo_toolkit`.
"""

from __future__ import annotations

from pathlib import Path


class NemoMarbleNetVADProvider:
    def __init__(
        self,
        *,
        model_path: str,
        threshold: float = 0.5,
        min_silence_duration_ms: int = 150,
        min_speech_duration_ms: int = 250,
        target_max_segment_s: float | None = None,
        split_threshold: float | None = None,
        split_search_backtrack_ratio: float = 0.4,
        split_search_forward_ratio: float = 0.1,
        split_gap_s: float = 0.0,
        frame_hop_s: float = 0.02,
        device: str | None = None,
    ):
        self.model_path = str(model_path)
        self.threshold = float(threshold)
        self.min_silence_s = max(0.0, float(min_silence_duration_ms) / 1000.0)
        self.min_speech_s = max(0.0, float(min_speech_duration_ms) / 1000.0)
        self.frame_hop_s = max(0.001, float(frame_hop_s))
        self.device = device
        self.target_max_segment_s = None if target_max_segment_s is None else float(target_max_segment_s)
        self.split_threshold = None if split_threshold is None else float(split_threshold)
        self.split_search_backtrack_ratio = float(split_search_backtrack_ratio)
        self.split_search_forward_ratio = float(split_search_forward_ratio)
        self.split_gap_s = max(0.0, float(split_gap_s))

        self._model = None
        self.last_regions: list[tuple[float, float]] | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            import nemo.collections.asr as nemo_asr  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "NeMo MarbleNet VAD requires `nemo_toolkit`. "
                "Install it in worker env via `uv add --project apps/worker nemo_toolkit[asr]`."
            ) from exc

        model_path = Path(self.model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"NeMo VAD model not found: {model_path}")

        model = nemo_asr.models.EncDecFrameClassificationModel.restore_from(
            restore_path=str(model_path),
            strict=False,
        )
        if self.device:
            dev = torch.device(self.device)
        else:
            dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(dev)
        model.eval()
        self._model = model

    @staticmethod
    def _merge_close_segments(
        segments: list[tuple[float, float]],
        *,
        max_gap_s: float,
    ) -> list[tuple[float, float]]:
        if not segments:
            return []
        merged: list[tuple[float, float]] = []
        cur_s, cur_e = segments[0]
        for s, e in segments[1:]:
            if s - cur_e <= max_gap_s:
                cur_e = max(cur_e, e)
            else:
                merged.append((cur_s, cur_e))
                cur_s, cur_e = s, e
        merged.append((cur_s, cur_e))
        return merged

    def _postprocess(self, probs, duration_s: float) -> list[tuple[float, float]]:
        # probs: 1D torch.Tensor or list[float]
        import torch

        t = probs
        if not isinstance(t, torch.Tensor):
            t = torch.tensor(list(t), dtype=torch.float32)
        t = t.detach().float().cpu()

        # If logits, squash to [0, 1].
        if t.numel() > 0:
            min_v = float(t.min().item())
            max_v = float(t.max().item())
            if min_v < 0.0 or max_v > 1.0:
                t = torch.sigmoid(t)

        active = t >= float(self.threshold)
        idx = active.nonzero(as_tuple=False).flatten().tolist()
        if not idx:
            return []

        segments: list[tuple[float, float]] = []
        start_i = prev_i = int(idx[0])
        for i in idx[1:]:
            i = int(i)
            if i == prev_i + 1:
                prev_i = i
                continue
            start_s = start_i * self.frame_hop_s
            end_s = (prev_i + 1) * self.frame_hop_s
            segments.append((start_s, end_s))
            start_i = prev_i = i
        segments.append((start_i * self.frame_hop_s, (prev_i + 1) * self.frame_hop_s))

        segments = self._merge_close_segments(segments, max_gap_s=self.min_silence_s)
        regions = [(s, min(e, duration_s)) for s, e in segments if e - s >= self.min_speech_s]
        self.last_regions = list(regions)

        if self.target_max_segment_s is None or self.target_max_segment_s <= 0:
            return regions

        # VAD-aware splitting for long regions: prefer cutting at low-probability valleys.
        max_len_s = float(self.target_max_segment_s)
        valley_thr = (
            float(self.split_threshold)
            if self.split_threshold is not None
            else max(0.05, min(float(self.threshold) * 0.8, float(self.threshold) - 0.05))
        )
        min_valley_s = max(0.04, min(self.min_silence_s, 0.2))  # 40-200ms
        min_valley_frames = max(2, int(round(min_valley_s / self.frame_hop_s)))
        backtrack_ratio = max(0.0, float(self.split_search_backtrack_ratio))
        forward_ratio = max(0.0, float(self.split_search_forward_ratio))

        split_segments: list[tuple[float, float]] = []
        for seg_start, seg_end in regions:
            if seg_end - seg_start <= max_len_s:
                split_segments.append((seg_start, seg_end))
                continue

            start_frame = max(0, int(seg_start / self.frame_hop_s))
            end_frame = min(int(duration_s / self.frame_hop_s) + 1, int(seg_end / self.frame_hop_s) + 1)
            cursor_s = seg_start

            while seg_end - cursor_s > max_len_s:
                target_s = cursor_s + max_len_s
                target_frame = int(target_s / self.frame_hop_s)
                cursor_frame = int(cursor_s / self.frame_hop_s)
                search_lo = max(
                    start_frame,
                    target_frame - int(round(backtrack_ratio * max_len_s / self.frame_hop_s)),
                )
                search_lo = max(search_lo, cursor_frame + 1)
                search_hi = min(
                    end_frame,
                    target_frame + int(round(forward_ratio * max_len_s / self.frame_hop_s)),
                )
                if search_hi - search_lo < 4:
                    break

                window = t[search_lo:search_hi]
                # Find a contiguous valley below threshold, else fall back to minimum point.
                below = (window < valley_thr).tolist()
                best_cut_frame = None
                best_valley = None  # (valley_start_frame, valley_end_frame)
                run_start = None
                for i, is_below in enumerate(below):
                    if is_below and run_start is None:
                        run_start = i
                    if (not is_below) and run_start is not None:
                        run_len = i - run_start
                        if run_len >= min_valley_frames:
                            valley_start = search_lo + run_start
                            valley_end = search_lo + i
                            best_valley = (valley_start, valley_end)
                            best_cut_frame = valley_start + (valley_end - valley_start) // 2
                            break
                        run_start = None
                if best_cut_frame is None and run_start is not None:
                    run_len = len(below) - run_start
                    if run_len >= min_valley_frames:
                        valley_start = search_lo + run_start
                        valley_end = search_lo + len(below)
                        best_valley = (valley_start, valley_end)
                        best_cut_frame = valley_start + (valley_end - valley_start) // 2

                if best_cut_frame is None:
                    best_cut_frame = int(search_lo + int(window.argmin().item()))

                if best_valley is not None:
                    valley_start_frame, valley_end_frame = best_valley
                    end_s = max(cursor_s + 0.5, float(valley_start_frame) * self.frame_hop_s)
                    next_s = max(end_s, float(valley_end_frame) * self.frame_hop_s)
                    if end_s <= cursor_s or seg_end - next_s < 0.5:
                        break
                    split_segments.append((cursor_s, end_s))
                    cursor_s = next_s
                else:
                    cut_s = max(cursor_s + 0.5, float(best_cut_frame) * self.frame_hop_s)
                    if cut_s <= cursor_s or seg_end - cut_s < 0.5:
                        break
                    if self.split_gap_s > 0:
                        half = self.split_gap_s / 2.0
                        end_s = max(cursor_s + 0.5, cut_s - half)
                        next_s = min(seg_end, cut_s + half)
                        if end_s <= cursor_s or seg_end - next_s < 0.5:
                            break
                        split_segments.append((cursor_s, end_s))
                        cursor_s = next_s
                    else:
                        split_segments.append((cursor_s, cut_s))
                        cursor_s = cut_s

            split_segments.append((cursor_s, seg_end))

        split_segments = [(s, e) for s, e in split_segments if e - s >= self.min_speech_s]
        return split_segments

    def detect(self, audio_path: str) -> list[tuple[float, float]]:
        self._ensure_loaded()
        assert self._model is not None

        import torch
        import torchaudio

        wav, sr = torchaudio.load(str(audio_path))
        if wav.numel() == 0:
            return []
        if sr != 16000:
            wav = torchaudio.functional.resample(wav, sr, 16000)
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)

        input_signal = wav.to(dtype=torch.float32)
        input_signal_length = torch.tensor([input_signal.shape[1]], dtype=torch.long)
        device = next(self._model.parameters()).device
        with torch.no_grad():
            out = self._model(
                input_signal=input_signal.to(device),
                input_signal_length=input_signal_length.to(device),
            )

        # Common shapes: (B, T) or (B, T, C)
        if isinstance(out, torch.Tensor):
            logits = out
        else:
            logits = torch.as_tensor(out)
        if logits.dim() == 3:
            # assume last dim is class; pick speech class index 1 if binary
            if logits.shape[-1] >= 2:
                logits = logits[..., 1]
            else:
                logits = logits.squeeze(-1)
        if logits.dim() == 2:
            logits = logits[0]

        duration_s = float(input_signal.shape[1]) / 16000.0
        return self._postprocess(logits, duration_s)
