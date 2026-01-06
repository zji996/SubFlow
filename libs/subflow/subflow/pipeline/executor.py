"""Pipeline executor."""

from __future__ import annotations

from subflow.pipeline.context import PipelineContext
from subflow.stages.base import Stage
from subflow.exceptions import StageExecutionError


class PipelineExecutor:
    """流水线执行器"""

    def __init__(self, stages: list[Stage]):
        self.stages = stages

    async def run(self, initial_context: PipelineContext) -> PipelineContext:
        """顺序执行所有阶段"""
        context: PipelineContext = dict(initial_context)
        for stage in self.stages:
            if not stage.validate_input(context):
                raise StageExecutionError(stage.name, "input validation failed")
            context = await stage.execute(context)
        return context
