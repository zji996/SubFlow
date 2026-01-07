"""SubFlow exception hierarchy."""

from __future__ import annotations


class SubFlowError(Exception):
    """Base error for SubFlow."""


class ConfigurationError(SubFlowError):
    """Raised when configuration or inputs are invalid."""


class ProviderError(SubFlowError):
    """Raised when an external provider call fails."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message


class ArtifactNotFoundError(SubFlowError):
    """Raised when an expected artifact is missing."""


class StageExecutionError(SubFlowError):
    """Raised when a pipeline stage fails."""

    def __init__(self, stage: str, message: str, *, project_id: str | None = None) -> None:
        prefix = f"{stage}"
        if project_id:
            prefix = f"{prefix} (project_id={project_id})"
        super().__init__(f"{prefix}: {message}")
        self.stage = stage
        self.project_id = project_id
        self.message = message
