"""Artifact store interface and local implementation."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ArtifactStore(ABC):
    @abstractmethod
    async def save(self, project_id: str, stage: str, name: str, data: bytes) -> str:
        """Save artifact bytes and return a path/url identifier."""

    @abstractmethod
    async def load(self, project_id: str, stage: str, name: str) -> bytes:
        """Load artifact bytes."""

    @abstractmethod
    async def list(self, project_id: str, stage: str | None = None) -> list[str]:
        """List artifact identifiers."""

    async def save_text(self, project_id: str, stage: str, name: str, text: str) -> str:
        return await self.save(project_id, stage, name, text.encode("utf-8"))

    async def load_text(self, project_id: str, stage: str, name: str) -> str:
        return (await self.load(project_id, stage, name)).decode("utf-8")

    async def save_json(self, project_id: str, stage: str, name: str, obj: Any) -> str:
        raw = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        return await self.save(project_id, stage, name, raw)

    async def load_json(self, project_id: str, stage: str, name: str) -> Any:
        return json.loads(await self.load_text(project_id, stage, name))


class LocalArtifactStore(ArtifactStore):
    """Local filesystem artifact store for development."""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    def _path(self, project_id: str, stage: str, name: str) -> Path:
        safe_stage = stage.strip().replace("/", "_")
        safe_name = name.strip().replace("/", "_")
        return self.base_dir / "projects" / project_id / safe_stage / safe_name

    async def save(self, project_id: str, stage: str, name: str, data: bytes) -> str:
        path = self._path(project_id, stage, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    async def load(self, project_id: str, stage: str, name: str) -> bytes:
        path = self._path(project_id, stage, name)
        return path.read_bytes()

    async def list(self, project_id: str, stage: str | None = None) -> list[str]:
        base = self.base_dir / "projects" / project_id
        if stage:
            base = base / stage
        if not base.exists():
            return []
        return [str(p) for p in base.rglob("*") if p.is_file()]
