from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from subflow.config import Settings
from subflow.exceptions import ConfigurationError, StageExecutionError
from subflow.services.blob_store import ProjectFileRef
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

    async def normalize_audio(
        self, input_path: str, output_path: str, *, target_db: float = -1.0
    ) -> str:  # noqa: ARG002
        src = Path(input_path)
        dst = Path(output_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes() + b"normalized")
        return str(dst)


class _CacheHitProvider(_DummyAudioProvider):
    async def separate_vocals(self, audio_path: str, output_dir: str) -> str:  # noqa: ARG002
        raise AssertionError("separate_vocals should not run on cache hit")


class _CountingNormalizeProvider(_DummyAudioProvider):
    def __init__(self) -> None:
        self.normalize_calls = 0

    async def normalize_audio(
        self, input_path: str, output_path: str, *, target_db: float = -1.0
    ) -> str:  # noqa: ARG002
        self.normalize_calls += 1
        return await super().normalize_audio(input_path, output_path, target_db=target_db)


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


async def test_audio_preprocess_reuses_cached_vocals(tmp_path, monkeypatch) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )

    class _DummyBlobStore:
        def __init__(self, settings: Settings) -> None:
            self.base_dir = Path(settings.data_dir) / "blobs"
            self._cached_vocals_hash = "6" * 64
            self._normalize_enabled = bool(settings.audio.normalize)
            self._normalize_target_db = float(settings.audio.normalize_target_db)

        def blob_path(self, hash_hex: str) -> Path:
            h = (hash_hex or "").strip().lower()
            return self.base_dir / h[:2] / h[2:4] / h

        async def get_derived(self, *, transform: str, src_hash: str, params=None):  # noqa: ANN001,ARG002
            if transform != "demucs_vocals":
                return None
            if not src_hash:
                return None
            if self._normalize_enabled:
                if not isinstance(params, dict):
                    return None
                if params.get("normalize") is not True:
                    return None
                if float(params.get("normalize_target_db")) != self._normalize_target_db:
                    return None
            return self._cached_vocals_hash

        async def set_derived(
            self, *, transform: str, src_hash: str, dst_hash: str, params=None
        ) -> None:  # noqa: ANN001,ARG002
            raise AssertionError("set_derived should not be called on cache hit")

        async def ingest_hashed_file(
            self,
            *,
            project_id: str,  # noqa: ARG002
            file_type: str,
            local_path: str,
            hash_hex: str,
            size_bytes: int,  # noqa: ARG002
            original_filename: str | None = None,
            mime_type: str | None = None,  # noqa: ARG002
            move: bool = False,
        ) -> ProjectFileRef:
            src = Path(local_path)
            dst = self.blob_path(hash_hex)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if move and src.exists() and not dst.exists():
                src.replace(dst)
            return ProjectFileRef(
                file_type=file_type,  # type: ignore[arg-type]
                blob_hash=hash_hex,
                path=str(dst if dst.exists() else src),
                original_filename=original_filename,
            )

        async def ingest_file(
            self,
            *,
            project_id: str,
            file_type: str,
            local_path: str,
            original_filename: str | None = None,
            mime_type: str | None = None,
            move: bool = False,
        ) -> ProjectFileRef:
            p = Path(local_path)
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            return await self.ingest_hashed_file(
                project_id=project_id,
                file_type=file_type,
                local_path=local_path,
                hash_hex=h,
                size_bytes=p.stat().st_size,
                original_filename=original_filename,
                mime_type=mime_type,
                move=move,
            )

    import subflow.stages.audio_preprocess as ap

    monkeypatch.setattr(ap, "BlobStore", _DummyBlobStore)

    stage = AudioPreprocessStage(settings)
    stage.provider = _CacheHitProvider()  # type: ignore[assignment]

    local_video = tmp_path / "video.mp4"
    local_video.write_bytes(b"video")

    cached_hash = "6" * 64
    cached_path = (
        Path(settings.data_dir) / "blobs" / cached_hash[:2] / cached_hash[2:4] / cached_hash
    )
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"cached vocals")

    out = await stage.execute({"project_id": "p1", "media_url": str(local_video)})

    assert Path(out["audio_path"]).exists()
    assert out["vocals_audio_path"] == str(cached_path)


async def test_audio_preprocess_skips_normalize_when_disabled(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
        audio={"normalize": False},
    )
    stage = AudioPreprocessStage(settings)
    provider = _CountingNormalizeProvider()
    stage.provider = provider  # type: ignore[assignment]

    local_video = tmp_path / "video.mp4"
    local_video.write_bytes(b"video")

    out = await stage.execute({"project_id": "p1", "media_url": str(local_video)})

    assert Path(out["vocals_audio_path"]).exists()
    assert provider.normalize_calls == 0


async def test_audio_preprocess_normalizes_when_enabled(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
        audio={"normalize": True, "normalize_target_db": -1.0},
    )
    stage = AudioPreprocessStage(settings)
    provider = _CountingNormalizeProvider()
    stage.provider = provider  # type: ignore[assignment]

    local_video = tmp_path / "video.mp4"
    local_video.write_bytes(b"video")

    out = await stage.execute({"project_id": "p1", "media_url": str(local_video)})

    assert Path(out["vocals_audio_path"]).exists()
    assert provider.normalize_calls == 1
