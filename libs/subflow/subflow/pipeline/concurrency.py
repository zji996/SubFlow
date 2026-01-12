from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

from subflow.config import Settings

ServiceType = Literal["asr", "llm_fast", "llm_power"]


@dataclass(frozen=True)
class ConcurrencyState:
    active: int
    max: int


class ConcurrencyTracker:
    def __init__(self, *, maxima: dict[ServiceType, int]) -> None:
        self._lock = asyncio.Lock()
        self._active: dict[ServiceType, int] = {k: 0 for k in maxima}
        self._max: dict[ServiceType, int] = {k: max(1, int(v)) for k, v in maxima.items()}

    def update_maxima(self, maxima: dict[ServiceType, int]) -> None:
        for key, value in maxima.items():
            self._max[key] = max(1, int(value))
            self._active.setdefault(key, 0)

    async def snapshot(self, service: ServiceType) -> ConcurrencyState:
        async with self._lock:
            return ConcurrencyState(active=int(self._active.get(service, 0)), max=int(self._max.get(service, 1)))

    @asynccontextmanager
    async def acquire(self, service: ServiceType) -> AsyncIterator[ConcurrencyState]:
        async with self._lock:
            self._active[service] = int(self._active.get(service, 0)) + 1
            state = ConcurrencyState(active=int(self._active[service]), max=int(self._max.get(service, 1)))
        try:
            yield state
        finally:
            async with self._lock:
                current = int(self._active.get(service, 0)) - 1
                self._active[service] = max(0, current)


_TRACKER: ConcurrencyTracker | None = None


def get_concurrency_tracker(settings: Settings | None = None) -> ConcurrencyTracker:
    global _TRACKER
    maxima: dict[ServiceType, int]
    if settings is not None:
        maxima = {
            "asr": int(settings.concurrency.asr),
            "llm_fast": int(settings.concurrency.llm_fast),
            "llm_power": int(settings.concurrency.llm_power),
        }
    else:
        maxima = {"asr": 1, "llm_fast": 1, "llm_power": 1}

    if _TRACKER is None:
        _TRACKER = ConcurrencyTracker(maxima=maxima)
    else:
        _TRACKER.update_maxima(maxima)
    return _TRACKER

