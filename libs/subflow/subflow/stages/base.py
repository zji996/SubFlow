"""Stage abstractions for pipeline execution."""

from __future__ import annotations

from abc import ABC, abstractmethod

from subflow.pipeline.context import PipelineContext


class Stage(ABC):
    """流水线阶段抽象基类"""

    name: str

    @abstractmethod
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """执行阶段逻辑，返回更新后的 context"""

    @abstractmethod
    def validate_input(self, context: PipelineContext) -> bool:
        """校验输入是否满足要求"""
