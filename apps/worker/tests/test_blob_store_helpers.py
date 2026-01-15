from __future__ import annotations

from pathlib import Path

from subflow.config import Settings
from subflow.services.blob_store import BlobStore, sha256_file


async def test_sha256_file_streaming(tmp_path) -> None:
    p = tmp_path / "a.bin"
    p.write_bytes(b"hello")
    h, size = sha256_file(p)
    assert size == 5
    assert h == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


async def test_blob_path_layout(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )
    store = BlobStore(settings)
    h = "a" * 64
    p = store.blob_path(h)
    assert p == Path(settings.data_dir) / "blobs" / "aa" / "aa" / h
