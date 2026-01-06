"""Pipeline orchestration.

This package is imported by pipeline stages for type hints. Keep imports lazy to
avoid circular-import issues between `subflow.pipeline` and `subflow.stages`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from subflow.pipeline.executor import PipelineExecutor
    from subflow.pipeline.orchestrator import PipelineOrchestrator
    from subflow.pipeline.factory import create_translation_pipeline

__all__ = ["PipelineExecutor", "PipelineOrchestrator", "create_translation_pipeline"]


def __getattr__(name: str) -> Any:
    if name == "PipelineExecutor":
        from subflow.pipeline.executor import PipelineExecutor

        return PipelineExecutor
    if name == "PipelineOrchestrator":
        from subflow.pipeline.orchestrator import PipelineOrchestrator

        return PipelineOrchestrator
    if name == "create_translation_pipeline":
        from subflow.pipeline.factory import create_translation_pipeline

        return create_translation_pipeline
    raise AttributeError(name)
