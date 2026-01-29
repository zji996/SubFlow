from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from subflow.stages.audio_preprocess import AudioPreprocessStage
from subflow.stages.vad import VADStage


@dataclass
class _ProgressRecorder:
    calls: list[tuple[int, str]]

    async def report(self, progress: int, message: str) -> None:
        self.calls.append((int(progress), str(message)))


@pytest.mark.asyncio
async def test_audio_preprocess_reports_progress(settings, monkeypatch, tmp_path) -> None:
    class _FakeAudioProvider:
        async def extract_audio(self, _video_path: str, audio_path: str) -> None:
            Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
            Path(audio_path).write_bytes(b"wav")

        async def separate_vocals(self, _audio_path: str, out_dir: str) -> Path:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            vocals_path = Path(out_dir) / "vocals.wav"
            vocals_path.write_bytes(b"vocals")
            return vocals_path

        async def normalize_audio(self, in_path: str, out_path: str, *, target_db: float) -> Path:  # noqa: ARG002
            Path(out_path).write_bytes(Path(in_path).read_bytes())
            return Path(out_path)

    class _FakeBlobStore:
        def __init__(self, _settings) -> None:  # noqa: ANN001
            return None

        async def ingest_file(
            self,
            *,
            project_id: str,  # noqa: ARG002
            file_type: str,  # noqa: ARG002
            local_path: str,
            original_filename: str,  # noqa: ARG002
            mime_type: str | None,  # noqa: ARG002
            move: bool,  # noqa: ARG002
        ):
            return SimpleNamespace(path=str(local_path), blob_hash=None)

        async def ingest_hashed_file(
            self,
            *,
            project_id: str,  # noqa: ARG002
            file_type: str,  # noqa: ARG002
            local_path: str,
            hash_hex: str,
            size_bytes: int,  # noqa: ARG002
            original_filename: str,  # noqa: ARG002
            mime_type: str | None,  # noqa: ARG002
            move: bool,  # noqa: ARG002
        ):
            return SimpleNamespace(path=str(local_path), blob_hash=str(hash_hex))

        async def get_derived(self, *, transform: str, src_hash: str, params: dict) -> str | None:  # noqa: ARG002
            return None

        def blob_path(self, blob_hash: str) -> Path:  # noqa: ARG002
            return tmp_path / "blobs" / "x"

        async def set_derived(
            self,
            *,
            transform: str,  # noqa: ARG002
            src_hash: str,  # noqa: ARG002
            dst_hash: str,  # noqa: ARG002
            params: dict,  # noqa: ARG002
        ) -> None:
            return None

    monkeypatch.setattr(
        "subflow.stages.audio_preprocess.get_audio_provider", lambda _cfg: _FakeAudioProvider()
    )
    monkeypatch.setattr("subflow.stages.audio_preprocess.BlobStore", _FakeBlobStore)

    stage = AudioPreprocessStage(settings)
    recorder = _ProgressRecorder(calls=[])

    video = tmp_path / "in.mp4"
    video.write_bytes(b"mp4")

    out = await stage.execute(
        {"project_id": "p1", "media_url": str(video)},
        progress_reporter=recorder,
    )

    assert recorder.calls
    assert recorder.calls[0][0] == 0
    assert recorder.calls[-1][0] == 100
    assert "audio_path" in out
    assert "vocals_audio_path" in out


@pytest.mark.asyncio
async def test_vad_reports_progress(settings, monkeypatch, tmp_path) -> None:
    class _FakeVADProvider:
        def detect(self, _audio_path: str):
            return [(0.0, 1.0)]

    monkeypatch.setattr("subflow.stages.vad.get_vad_provider", lambda _cfg: _FakeVADProvider())
    stage = VADStage(settings)
    recorder = _ProgressRecorder(calls=[])

    audio = tmp_path / "vocals.wav"
    audio.write_bytes(b"wav")

    out = await stage.execute({"vocals_audio_path": str(audio)}, progress_reporter=recorder)
    assert recorder.calls == [(0, "VAD 检测中..."), (100, "VAD 检测完成")]
    assert out["vad_regions"]
