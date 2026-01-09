from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from subflow.config import Settings

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
def app(settings: Settings, redis: FakeRedis) -> FastAPI:
    from routes.projects import router as projects_router

    test_app = FastAPI()
    test_app.state.redis = redis
    test_app.state.settings = settings
    test_app.include_router(projects_router)
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)
