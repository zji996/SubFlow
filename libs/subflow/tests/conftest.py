from __future__ import annotations

import pytest

from subflow.config import Settings


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        artifact_store_backend="local",
        data_dir=str(tmp_path / "data"),
        models_dir=str(tmp_path / "models"),
        log_dir=str(tmp_path / "logs"),
    )
