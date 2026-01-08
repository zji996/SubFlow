from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from subflow.config import Settings
from subflow.exceptions import ConfigurationError, StageExecutionError
from subflow.stages.audio_preprocess import AudioPreprocessStage


class _DummyAudioProvider:
    async def extract_audio(self, input_path: str, output_path: str) -> None:  # noqa: ARG002
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"")

    async def separate_vocals(self, audio_path: str, output_dir: str) -> str:  # noqa: ARG002
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out = Path(output_dir) / "vocals.wav"
        out.write_bytes(b"")
        return str(out)


async def test_audio_preprocess_rejects_unsupported_media_url(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )
    stage = AudioPreprocessStage(settings)

    with pytest.raises(ConfigurationError):
        await stage.execute({"project_id": "p1", "media_url": "ftp://example.com/a.mp4"})


async def test_audio_preprocess_rejects_missing_local_path(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )
    stage = AudioPreprocessStage(settings)

    with pytest.raises(ConfigurationError):
        await stage.execute({"project_id": "p1", "media_url": str(tmp_path / "missing.mp4")})


async def test_audio_preprocess_wraps_download_errors(tmp_path, monkeypatch) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )
    stage = AudioPreprocessStage(settings)

    class _FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method: str, url: str, timeout: float = 0):  # noqa: ARG002
            class _Stream:
                async def __aenter__(self):
                    raise httpx.ConnectError("boom", request=httpx.Request(method, url))

                async def __aexit__(self, *args):
                    return False

            return _Stream()

    import subflow.stages.audio_preprocess as ap

    monkeypatch.setattr(ap.httpx, "AsyncClient", _FailingClient)

    with pytest.raises(StageExecutionError):
        await stage.execute({"project_id": "p1", "media_url": "https://example.com/a.mp4"})


async def test_audio_preprocess_uses_existing_video_path(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )
    stage = AudioPreprocessStage(settings)
    stage.provider = _DummyAudioProvider()  # type: ignore[assignment]

    local_video = tmp_path / "video.mp4"
    local_video.write_bytes(b"")

    out = await stage.execute(
        {
            "project_id": "p1",
            "media_url": "https://example.com/ignored.mp4",
            "video_path": str(local_video),
        }
    )

    assert out["video_path"] == str(local_video)
    assert Path(out["audio_path"]).exists()
    assert Path(out["vocals_audio_path"]).exists()
