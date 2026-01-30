from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from subflow.repositories import ProjectRepository
from subflow.storage.artifact_store import LocalArtifactStore


@pytest.mark.asyncio
async def test_local_artifact_store_list_project_ids_lists_directories(tmp_path: Path) -> None:
    base_dir = tmp_path / "data"
    store = LocalArtifactStore(str(base_dir))

    (base_dir / "projects" / "proj_a" / "stage1").mkdir(parents=True)
    (base_dir / "projects" / "proj_b" / "stage2").mkdir(parents=True)
    (base_dir / "projects" / "proj_a" / "stage1" / "a.json").write_text("{}", encoding="utf-8")
    (base_dir / "projects" / "proj_b" / "stage2" / "b.json").write_text("{}", encoding="utf-8")

    assert await store.list_project_ids() == ["proj_a", "proj_b"]


@pytest.mark.asyncio
async def test_local_artifact_store_delete_project_removes_tree_and_counts_files(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "data"
    store = LocalArtifactStore(str(base_dir))

    p = base_dir / "projects" / "proj_x"
    (p / "stage1").mkdir(parents=True)
    (p / "stage2").mkdir(parents=True)
    (p / "stage1" / "a.json").write_text("{}", encoding="utf-8")
    (p / "stage2" / "b.json").write_text("{}", encoding="utf-8")
    (p / "stage2" / "c.bin").write_bytes(b"123")

    deleted = await store.delete_project("proj_x")
    assert deleted == 3
    assert not p.exists()


class _FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]):
        self._rows = rows
        self._executed: list[tuple[str, tuple[object, ...] | None]] = []

    @property
    def executed(self) -> list[tuple[str, tuple[object, ...] | None]]:
        return list(self._executed)

    async def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self._executed.append((sql, params))

    async def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None

    async def __aenter__(self) -> "_FakeCursor":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


class _FakeConn:
    def __init__(self, rows: list[tuple[object, ...]]):
        self._rows = rows

    @asynccontextmanager
    async def cursor(self, *args, **kwargs):  # noqa: ANN001
        yield _FakeCursor(self._rows)


class _FakePool:
    def __init__(self, rows: list[tuple[object, ...]]):
        self._rows = rows

    @asynccontextmanager
    async def connection(self):
        yield _FakeConn(self._rows)


@pytest.mark.asyncio
async def test_project_repo_list_all_ids_returns_ids() -> None:
    repo = ProjectRepository(_FakePool([("proj_1",), ("proj_2",)]))
    assert await repo.list_all_ids() == ["proj_1", "proj_2"]

