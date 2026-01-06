"""Stage abstractions for pipeline execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Stage(ABC):
    """流水线阶段抽象基类"""

    name: str

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """执行阶段逻辑，返回更新后的 context"""

    @abstractmethod
    def validate_input(self, context: dict[str, Any]) -> bool:
        """校验输入是否满足要求"""

