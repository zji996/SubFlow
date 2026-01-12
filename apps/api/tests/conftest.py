from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from subflow.config import Settings
from subflow.models.project import Project, ProjectStatus, StageRun
from subflow.models.segment import ASRSegment, SemanticChunk
from subflow.models.subtitle_export import SubtitleExport

_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))


class FakeRedis:
    def __init__(self) -> None:
        self._kv: dict[str, str] = {}
        self._sets: dict[str, set[str]] = defaultdict(set)
        self._lists: dict[str, list[str]] = defaultdict(list)

    async def get(self, key: str) -> str | None:
        return self._kv.get(str(key))

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:  # noqa: ARG002
        self._kv[str(key)] = str(value)
        return True

    async def delete(self, key: str) -> int:
        existed = str(key) in self._kv
        self._kv.pop(str(key), None)
        return 1 if existed else 0

    async def sadd(self, key: str, *values: str) -> int:
        s = self._sets[str(key)]
        before = len(s)
        for v in values:
            s.add(str(v))
        return len(s) - before

    async def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(str(key), set()))

    async def srem(self, key: str, *values: str) -> int:
        s = self._sets.get(str(key), set())
        removed = 0
        for v in values:
            if str(v) in s:
                s.remove(str(v))
                removed += 1
        return removed

    async def lpush(self, key: str, *values: str) -> int:
        lst = self._lists[str(key)]
        for v in values:
            lst.insert(0, str(v))
        return len(lst)

    async def aclose(self) -> None:
        return None

    def dump_queue(self, key: str) -> list[dict[str, Any]]:
        return [json.loads(x) for x in list(self._lists.get(str(key), []))]


@dataclass
class InMemoryPool:
    projects: dict[str, Project] = field(default_factory=dict)
    stage_runs: dict[tuple[str, str], StageRun] = field(default_factory=dict)
    exports: dict[str, list[SubtitleExport]] = field(default_factory=dict)
    asr_segments: dict[str, list[ASRSegment]] = field(default_factory=dict)
    asr_corrections: dict[str, dict[int, str]] = field(default_factory=dict)
    semantic_chunks: dict[str, list[SemanticChunk]] = field(default_factory=dict)


class FakeProjectRepository:
    def __init__(self, pool: InMemoryPool) -> None:
        self.pool = pool

    async def create(self, project: Project) -> Project:
        self.pool.projects[project.id] = project
        return project

    async def get(self, project_id: str) -> Project | None:
        return self.pool.projects.get(str(project_id))

    async def update(self, project: Project) -> Project:
        self.pool.projects[project.id] = project
        return project

    async def delete(self, project_id: str) -> bool:
        pid = str(project_id)
        existed = pid in self.pool.projects
        self.pool.projects.pop(pid, None)
        # cascade-like cleanup
        self.pool.stage_runs = {
            (p, s): sr for (p, s), sr in self.pool.stage_runs.items() if p != pid
        }
        self.pool.exports.pop(pid, None)
        self.pool.asr_segments.pop(pid, None)
        self.pool.asr_corrections.pop(pid, None)
        self.pool.semantic_chunks.pop(pid, None)
        return existed

    async def list(self, limit: int = 100, offset: int = 0) -> list[Project]:
        items = list(self.pool.projects.values())
        return items[int(offset) : int(offset) + int(limit)]

    async def update_status(
        self,
        project_id: str,
        status: str,
        current_stage: int | None = None,
        *,
        error_message: str | None = None,  # noqa: ARG002
    ) -> None:
        proj = self.pool.projects.get(str(project_id))
        if proj is None:
            return
        proj.status = ProjectStatus(str(status))
        if current_stage is not None:
            proj.current_stage = int(current_stage)


class FakeStageRunRepository:
    def __init__(self, pool: InMemoryPool) -> None:
        self.pool = pool

    async def get(self, project_id: str, stage: str) -> StageRun | None:
        return self.pool.stage_runs.get((str(project_id), str(stage)))

    async def list_by_project(self, project_id: str) -> list[StageRun]:
        pid = str(project_id)
        return [sr for (p, _s), sr in self.pool.stage_runs.items() if p == pid]


class FakeSubtitleExportRepository:
    def __init__(self, pool: InMemoryPool) -> None:
        self.pool = pool

    async def create(self, export: SubtitleExport) -> SubtitleExport:
        self.pool.exports.setdefault(export.project_id, []).append(export)
        return export

    async def list_by_project(self, project_id: str) -> list[SubtitleExport]:
        return list(self.pool.exports.get(str(project_id), []))


class FakeASRSegmentRepository:
    def __init__(self, pool: InMemoryPool) -> None:
        self.pool = pool

    async def get_by_project(
        self, project_id: str, *, use_corrected: bool = False
    ) -> list[ASRSegment]:
        pid = str(project_id)
        segs = list(self.pool.asr_segments.get(pid, []))
        if not use_corrected:
            return segs
        corrected = self.pool.asr_corrections.get(pid, {})
        out: list[ASRSegment] = []
        for seg in segs:
            text = seg.text
            if int(seg.id) in corrected:
                text = corrected[int(seg.id)]
            out.append(
                ASRSegment(
                    id=seg.id, start=seg.start, end=seg.end, text=text, language=seg.language
                )
            )
        return out

    async def get_corrected_map(self, project_id: str) -> dict[int, str]:
        return dict(self.pool.asr_corrections.get(str(project_id), {}))


class FakeSemanticChunkRepository:
    def __init__(self, pool: InMemoryPool) -> None:
        self.pool = pool

    async def get_by_project(self, project_id: str) -> list[SemanticChunk]:
        return list(self.pool.semantic_chunks.get(str(project_id), []))


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        artifact_store_backend="local",
        data_dir=str(tmp_path / "data"),
        models_dir=str(tmp_path / "models"),
        log_dir=str(tmp_path / "logs"),
    )


@pytest.fixture()
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture()
def db_pool() -> InMemoryPool:
    return InMemoryPool()


@pytest.fixture(autouse=True)
def patch_repos(monkeypatch, db_pool: InMemoryPool) -> None:
    monkeypatch.setattr("services.project_service.ProjectRepository", FakeProjectRepository)
    monkeypatch.setattr("services.project_service.StageRunRepository", FakeStageRunRepository)
    monkeypatch.setattr(
        "services.project_service.SubtitleExportRepository", FakeSubtitleExportRepository
    )

    monkeypatch.setattr("routes.projects.ASRSegmentRepository", FakeASRSegmentRepository)
    monkeypatch.setattr("routes.projects.SemanticChunkRepository", FakeSemanticChunkRepository)
    monkeypatch.setattr("routes.projects.StageRunRepository", FakeStageRunRepository)
    monkeypatch.setattr("routes.projects.SubtitleExportRepository", FakeSubtitleExportRepository)


@pytest.fixture()
def app(settings: Settings, redis: FakeRedis, db_pool: InMemoryPool) -> FastAPI:
    from routes.projects import router as projects_router
    from routes.uploads import router as uploads_router

    test_app = FastAPI()
    test_app.state.redis = redis
    test_app.state.settings = settings
    test_app.state.db_pool = db_pool
    test_app.include_router(projects_router)
    test_app.include_router(uploads_router)
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)
