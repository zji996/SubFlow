"""Projects API routes."""

from __future__ import annotations

from fastapi import APIRouter

from subflow.repositories import (
    ASRSegmentRepository,
    GlobalContextRepository,
    SemanticChunkRepository,
    StageRunRepository,
    SubtitleExportRepository,
)

from .artifacts import router as artifacts_router
from .core import router as core_router
from .execution import router as execution_router
from .exports import router as exports_router
from .preview import router as preview_router
from .subtitles import router as subtitles_router

router = APIRouter()
router.include_router(core_router, prefix="/projects", tags=["projects"])
router.include_router(execution_router, prefix="/projects", tags=["projects"])
router.include_router(preview_router, prefix="/projects", tags=["projects"])
router.include_router(artifacts_router, prefix="/projects", tags=["projects"])
router.include_router(exports_router, prefix="/projects", tags=["projects"])
router.include_router(subtitles_router, prefix="/projects", tags=["projects"])

__all__ = [
    "ASRSegmentRepository",
    "GlobalContextRepository",
    "SemanticChunkRepository",
    "StageRunRepository",
    "SubtitleExportRepository",
    "router",
]
