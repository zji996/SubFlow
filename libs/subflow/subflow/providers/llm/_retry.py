"""Shared retry utilities for LLM providers."""

from __future__ import annotations

import logging
from collections.abc import Callable

from tenacity import RetryCallState, wait_exponential

from subflow.error_codes import ErrorCode
from subflow.exceptions import ProviderError

_WAIT_NORMAL = wait_exponential(min=1, max=10)
_WAIT_RATE_LIMIT = wait_exponential(min=2, max=30)


class RetryableLLMError(ProviderError):
    """Retryable LLM error with rate limit tracking."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        rate_limited: bool = False,
        error_code: ErrorCode | str | None = None,
    ) -> None:
        super().__init__(provider, message, error_code=error_code)
        self.rate_limited = bool(rate_limited)


def wait_retry(state: RetryCallState) -> float:
    exc = state.outcome.exception() if state.outcome else None
    if isinstance(exc, RetryableLLMError) and exc.rate_limited:
        return _WAIT_RATE_LIMIT(state)
    return _WAIT_NORMAL(state)


def log_retry(logger: logging.Logger) -> Callable[[RetryCallState], None]:
    def _log(state: RetryCallState) -> None:
        exc = state.outcome.exception() if state.outcome else None
        provider = "llm"
        model = None
        if state.args:
            provider = getattr(state.args[0], "provider", provider)
            model = getattr(state.args[0], "model", None)
        wait_s = state.next_action.sleep if state.next_action else None
        logger.warning(
            "llm retrying (provider=%s, model=%s, attempt=%s, wait_s=%s, error=%s)",
            provider,
            model,
            state.attempt_number,
            wait_s,
            exc,
        )

    return _log

