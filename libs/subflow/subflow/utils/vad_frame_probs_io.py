"""Serialize / deserialize VAD frame-level probabilities for artifact storage."""

from __future__ import annotations

import struct
import sys
from array import array
from collections.abc import Iterable


_MAGIC = b"SFVADP1\x00"
_HEADER_STRUCT = struct.Struct("<8s d I")


def _as_float32_array(frame_probs: object) -> array:
    if isinstance(frame_probs, array):
        arr = frame_probs
        if arr.typecode != "f":
            out = array("f")
            out.fromlist([float(x) for x in arr])
            return out
        return arr

    tolist = getattr(frame_probs, "tolist", None)
    if callable(tolist):
        values = tolist()
        if isinstance(values, list):
            out = array("f")
            out.fromlist([float(v) for v in values])
            return out

    # Optional fast-path for torch.Tensor without hard depending on torch.
    detach = getattr(frame_probs, "detach", None)
    if callable(detach):
        try:
            import torch

            if isinstance(frame_probs, torch.Tensor):
                t = frame_probs.detach().to(dtype=torch.float32).cpu().contiguous()
                try:
                    data = t.numpy().tobytes()
                except Exception:
                    out = array("f")
                    out.fromlist([float(v) for v in t.tolist()])
                    return out
                out = array("f")
                out.frombytes(data)
                return out
        except Exception:
            pass

    out = array("f")
    if not isinstance(frame_probs, Iterable):
        return out
    try:
        for v in frame_probs:
            out.append(float(v))
    except TypeError:
        return out
    return out


def encode_vad_frame_probs(*, frame_probs: object, frame_hop_s: float) -> bytes:
    """Encode frame probs to a compact binary payload.

    Format (little-endian):
      - magic: 8 bytes
      - frame_hop_s: float64
      - count: uint32
      - values: float32[count]
    """
    hop = float(frame_hop_s)
    arr = _as_float32_array(frame_probs)
    count = int(len(arr))
    if sys.byteorder != "little":
        arr = array("f", arr)
        arr.byteswap()
    header = _HEADER_STRUCT.pack(_MAGIC, hop, count)
    return header + arr.tobytes()


def decode_vad_frame_probs(data: bytes) -> tuple[array, float]:
    """Decode payload into (float32 array('f'), frame_hop_s)."""
    raw = bytes(data or b"")
    if len(raw) < _HEADER_STRUCT.size:
        return (array("f"), 0.0)
    magic, hop, count = _HEADER_STRUCT.unpack(raw[: _HEADER_STRUCT.size])
    if magic != _MAGIC:
        return (array("f"), 0.0)
    values = raw[_HEADER_STRUCT.size :]
    out = array("f")
    out.frombytes(values)
    if sys.byteorder != "little":
        out.byteswap()
    if count and len(out) > count:
        del out[count:]
    return (out, float(hop))
