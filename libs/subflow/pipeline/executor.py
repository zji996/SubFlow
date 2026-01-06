"""Pipeline executor."""

from __future__ import annotations

from typing import Any

from libs.subflow.stages.base import Stage


class PipelineExecutor:
    """流水线执行器"""

    def __init__(self, stages: list[Stage]):
        self.stages = stages

    async def run(self, initial_context: dict[str, Any]) -> dict[str, Any]:
        """顺序执行所有阶段"""
        context: dict[str, Any] = dict(initial_context)
        for stage in self.stages:
            if not stage.validate_input(context):
                raise ValueError(f"Stage {stage.name} input validation failed")
            context = await stage.execute(context)
        return context

