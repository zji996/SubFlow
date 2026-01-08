"""SubFlow exception hierarchy."""

from __future__ import annotations

from subflow.error_codes import ErrorCode


class SubFlowError(Exception):
    """Base error for SubFlow."""


class ConfigurationError(SubFlowError):
    """Raised when configuration or inputs are invalid."""


class ProviderError(SubFlowError):
    """Raised when an external provider call fails."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        error_code: ErrorCode | str | None = None,
    ) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message
        self.error_code = error_code


class ArtifactNotFoundError(SubFlowError):
    """Raised when an expected artifact is missing."""


class StageExecutionError(SubFlowError):
    """Raised when a pipeline stage fails."""

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        project_id: str | None = None,
        error_code: ErrorCode | str | None = None,
    ) -> None:
        prefix = f"{stage}"
        if project_id:
            prefix = f"{prefix} (project_id={project_id})"
        super().__init__(f"{prefix}: {message}")
        self.stage = stage
        self.project_id = project_id
        self.message = message
        self.error_code = error_code
