"""LLM health monitoring (passive via real calls + optional manual probe).

Design goals:
- GET status never triggers LLM requests (read cached state only).
- Updates happen on real LLM calls (success/error/latency).
- Optional Redis persistence for cross-process visibility.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Coroutine, Literal

from redis.asyncio import Redis

from subflow.providers.llm import LLMCompletionResult, LLMProvider, Message


LLMProfile = Literal["fast", "power"]
ProviderHealthStatus = Literal["ok", "error", "unknown"]
OverallHealthStatus = Literal["healthy", "degraded", "unhealthy", "unknown"]

_STATE_TTL_S = 24 * 60 * 60
_WINDOW_S = 60 * 60


def _ts() -> float:
    return time.time()


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_profile(value: str) -> LLMProfile:
    name = str(value or "").strip().lower()
    if name == "power":
        return "power"
    return "fast"


def _truncate_error(value: str, limit: int = 500) -> str:
    s = str(value or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "..."


@dataclass
class _ProfileState:
    provider: str | None = None
    model: str | None = None

    last_success_ts: float | None = None
    last_error_ts: float | None = None
    last_error: str | None = None
    last_latency_ms: int | None = None

    # Sliding window events (in-memory only)
    success_events: deque[float] = field(default_factory=deque)
    error_events: deque[float] = field(default_factory=deque)


@dataclass(frozen=True)
class ProviderHealth:
    status: ProviderHealthStatus
    provider: str
    model: str
    last_success_at: str | None
    last_error_at: str | None
    last_error: str | None
    last_latency_ms: int | None
    success_count_1h: int
    error_count_1h: int


@dataclass(frozen=True)
class LLMHealthResponse:
    status: OverallHealthStatus
    providers: dict[LLMProfile, ProviderHealth]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "providers": {
                profile: {
                    "status": health.status,
                    "provider": health.provider,
                    "model": health.model,
                    "last_success_at": health.last_success_at,
                    "last_error_at": health.last_error_at,
                    "last_error": health.last_error,
                    "last_latency_ms": health.last_latency_ms,
                    "success_count_1h": health.success_count_1h,
                    "error_count_1h": health.error_count_1h,
                }
                for profile, health in self.providers.items()
            },
        }


class LLMHealthMonitor:
    def __init__(
        self,
        *,
        redis: Redis | None = None,
        stale_after_s: int | None = None,
        key_prefix: str = "subflow:health:llm",
    ) -> None:
        self._redis = redis
        self._key_prefix = str(key_prefix or "subflow:health:llm").rstrip(":")
        self._stale_after_s = int(
            stale_after_s
            if stale_after_s is not None
            else int(os.getenv("LLM_HEALTH_STALE_SECONDS", "600") or "600")
        )
        self._states: dict[LLMProfile, _ProfileState] = {
            "fast": _ProfileState(),
            "power": _ProfileState(),
        }

    def set_redis(self, redis: Redis | None) -> None:
        self._redis = redis

    def _state_key(self, profile: LLMProfile) -> str:
        return f"{self._key_prefix}:state:{profile}"

    def _events_key(self, profile: LLMProfile, kind: Literal["success", "error"]) -> str:
        return f"{self._key_prefix}:events:{profile}:{kind}"

    def _is_stale(self, state: _ProfileState, now_ts: float) -> bool:
        last = max(
            (state.last_success_ts or 0.0),
            (state.last_error_ts or 0.0),
        )
        if last <= 0.0:
            return False
        return (now_ts - last) > float(self._stale_after_s)

    @staticmethod
    def _derive_status(state: _ProfileState, now_ts: float, *, stale_after_s: int) -> ProviderHealthStatus:
        last_success = state.last_success_ts
        last_error = state.last_error_ts
        if last_success is None and last_error is None:
            return "unknown"

        last = max((last_success or 0.0), (last_error or 0.0))
        if last <= 0.0:
            return "unknown"
        if (now_ts - last) > float(stale_after_s):
            return "unknown"

        if last_success is not None and last_error is not None:
            return "ok" if last_success >= last_error else "error"
        if last_success is not None:
            return "ok"
        return "error"

    def _prune_deque(self, items: deque[float], now_ts: float) -> None:
        cutoff = now_ts - float(_WINDOW_S)
        while items and items[0] < cutoff:
            items.popleft()

    async def report_success(
        self,
        *,
        profile: str,
        provider: str,
        model: str,
        latency_ms: int | None,
        at_ts: float | None = None,
    ) -> None:
        try:
            await self._report(
                profile=_coerce_profile(profile),
                ok=True,
                provider=str(provider or "").strip(),
                model=str(model or "").strip(),
                latency_ms=latency_ms,
                error=None,
                at_ts=at_ts,
            )
        except Exception:
            return None

    async def report_error(
        self,
        *,
        profile: str,
        provider: str,
        model: str,
        latency_ms: int | None,
        error: str,
        at_ts: float | None = None,
    ) -> None:
        try:
            await self._report(
                profile=_coerce_profile(profile),
                ok=False,
                provider=str(provider or "").strip(),
                model=str(model or "").strip(),
                latency_ms=latency_ms,
                error=_truncate_error(error),
                at_ts=at_ts,
            )
        except Exception:
            return None

    async def _report(
        self,
        *,
        profile: LLMProfile,
        ok: bool,
        provider: str,
        model: str,
        latency_ms: int | None,
        error: str | None,
        at_ts: float | None,
    ) -> None:
        now_ts = float(at_ts if at_ts is not None else _ts())
        state = self._states[profile]
        state.provider = provider or state.provider
        state.model = model or state.model
        state.last_latency_ms = int(latency_ms) if latency_ms is not None else state.last_latency_ms

        if ok:
            state.last_success_ts = now_ts
            state.last_error = None
            state.success_events.append(now_ts)
        else:
            state.last_error_ts = now_ts
            state.last_error = error or "unknown error"
            state.error_events.append(now_ts)

        self._prune_deque(state.success_events, now_ts)
        self._prune_deque(state.error_events, now_ts)

        redis = self._redis
        if redis is None:
            return None

        payload = {
            "provider": state.provider,
            "model": state.model,
            "last_success_ts": state.last_success_ts,
            "last_error_ts": state.last_error_ts,
            "last_error": state.last_error,
            "last_latency_ms": state.last_latency_ms,
        }

        state_key = self._state_key(profile)
        success_key = self._events_key(profile, "success")
        error_key = self._events_key(profile, "error")

        pipe = redis.pipeline()
        pipe.set(state_key, json.dumps(payload, ensure_ascii=False), ex=_STATE_TTL_S)
        if ok:
            pipe.zadd(success_key, {str(now_ts): now_ts})
        else:
            pipe.zadd(error_key, {str(now_ts): now_ts})

        cutoff = now_ts - float(_WINDOW_S)
        pipe.zremrangebyscore(success_key, "-inf", cutoff)
        pipe.zremrangebyscore(error_key, "-inf", cutoff)
        pipe.expire(success_key, _STATE_TTL_S)
        pipe.expire(error_key, _STATE_TTL_S)
        await pipe.execute()

    async def _read_state_from_redis(self, profile: LLMProfile) -> _ProfileState | None:
        redis = self._redis
        if redis is None:
            return None
        raw = await redis.get(self._state_key(profile))
        if not raw:
            return None
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None

        out = _ProfileState()
        out.provider = str(obj.get("provider") or "").strip() or None
        out.model = str(obj.get("model") or "").strip() or None
        out.last_error = str(obj.get("last_error") or "").strip() or None

        for key in ("last_success_ts", "last_error_ts"):
            value = obj.get(key)
            if isinstance(value, (int, float)):
                setattr(out, key, float(value))
        latency = obj.get("last_latency_ms")
        if isinstance(latency, int):
            out.last_latency_ms = int(latency)
        return out

    async def _counts_1h(self, profile: LLMProfile) -> tuple[int, int]:
        now_ts = _ts()
        state = self._states[profile]

        redis = self._redis
        if redis is None:
            self._prune_deque(state.success_events, now_ts)
            self._prune_deque(state.error_events, now_ts)
            return len(state.success_events), len(state.error_events)

        cutoff = now_ts - float(_WINDOW_S)
        success_key = self._events_key(profile, "success")
        error_key = self._events_key(profile, "error")
        pipe = redis.pipeline()
        pipe.zcount(success_key, cutoff, "+inf")
        pipe.zcount(error_key, cutoff, "+inf")
        success, error = await pipe.execute()
        return int(success or 0), int(error or 0)

    async def provider_health(
        self,
        *,
        profile: str,
        configured_provider: str,
        configured_model: str,
    ) -> ProviderHealth:
        p = _coerce_profile(profile)
        now_ts = _ts()

        state = await self._read_state_from_redis(p)
        if state is None:
            state = self._states[p]

        success_1h, error_1h = await self._counts_1h(p)

        provider = str(state.provider or "").strip() or str(configured_provider or "").strip() or "unknown"
        model = str(state.model or "").strip() or str(configured_model or "").strip() or "unknown"

        status = self._derive_status(state, now_ts, stale_after_s=self._stale_after_s)
        # Keep timestamps as-is (even if stale), but surface "unknown" status to callers.
        return ProviderHealth(
            status=status,
            provider=provider,
            model=model,
            last_success_at=_iso(state.last_success_ts),
            last_error_at=_iso(state.last_error_ts),
            last_error=state.last_error,
            last_latency_ms=state.last_latency_ms,
            success_count_1h=int(success_1h),
            error_count_1h=int(error_1h),
        )

    @staticmethod
    def overall_status(providers: dict[LLMProfile, ProviderHealth]) -> OverallHealthStatus:
        statuses = [p.status for p in providers.values()]
        if all(s == "unknown" for s in statuses):
            return "unknown"
        if all(s == "ok" for s in statuses):
            return "healthy"
        if all(s == "error" for s in statuses):
            return "unhealthy"
        return "degraded"

    async def snapshot(
        self,
        *,
        fast_provider: str,
        fast_model: str,
        power_provider: str,
        power_model: str,
    ) -> LLMHealthResponse:
        providers: dict[LLMProfile, ProviderHealth] = {
            "fast": await self.provider_health(
                profile="fast",
                configured_provider=fast_provider,
                configured_model=fast_model,
            ),
            "power": await self.provider_health(
                profile="power",
                configured_provider=power_provider,
                configured_model=power_model,
            ),
        }
        return LLMHealthResponse(status=self.overall_status(providers), providers=providers)


_LLM_MONITOR: LLMHealthMonitor | None = None


def get_llm_health_monitor() -> LLMHealthMonitor:
    global _LLM_MONITOR
    if _LLM_MONITOR is None:
        _LLM_MONITOR = LLMHealthMonitor(redis=None)
    return _LLM_MONITOR


def init_llm_health_monitor(*, redis: Redis | None, stale_after_s: int | None = None) -> LLMHealthMonitor:
    monitor = get_llm_health_monitor()
    monitor.set_redis(redis)
    if stale_after_s is not None:
        monitor._stale_after_s = int(stale_after_s)
    return monitor


def _fire_and_forget(coro: Coroutine[Any, Any, Any]) -> None:
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        return None

    # Avoid "Task exception was never retrieved" if the underlying coroutine fails.
    def _consume_result(t: asyncio.Task[Any]) -> None:
        try:
            _ = t.exception()
        except asyncio.CancelledError:
            return None
        except Exception:
            return None

    task.add_done_callback(_consume_result)


class HealthReportingLLMProvider(LLMProvider):
    """LLMProvider wrapper that updates LLMHealthMonitor (non-blocking)."""

    def __init__(
        self,
        inner: LLMProvider,
        *,
        monitor: LLMHealthMonitor,
        profile: str,
        provider: str,
        model: str,
    ) -> None:
        self._inner = inner
        self._monitor = monitor
        self._profile = str(profile or "fast")
        self._provider = str(provider or "").strip() or "unknown"
        self._model = str(model or "").strip() or "unknown"

    async def complete(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        started = time.perf_counter()
        try:
            out = await self._inner.complete(messages, temperature=temperature, max_tokens=max_tokens)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            _fire_and_forget(
                self._monitor.report_error(
                    profile=self._profile,
                    provider=self._provider,
                    model=self._model,
                    latency_ms=latency_ms,
                    error=str(exc),
                )
            )
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)
        _fire_and_forget(
            self._monitor.report_success(
                profile=self._profile,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
            )
        )
        return out

    async def complete_with_usage(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMCompletionResult:
        started = time.perf_counter()
        try:
            out = await self._inner.complete_with_usage(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            _fire_and_forget(
                self._monitor.report_error(
                    profile=self._profile,
                    provider=self._provider,
                    model=self._model,
                    latency_ms=latency_ms,
                    error=str(exc),
                )
            )
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)
        _fire_and_forget(
            self._monitor.report_success(
                profile=self._profile,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
            )
        )
        return out

    async def complete_json(
        self,
        messages: list[Message],
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            out = await self._inner.complete_json(messages, temperature=temperature)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            _fire_and_forget(
                self._monitor.report_error(
                    profile=self._profile,
                    provider=self._provider,
                    model=self._model,
                    latency_ms=latency_ms,
                    error=str(exc),
                )
            )
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)
        _fire_and_forget(
            self._monitor.report_success(
                profile=self._profile,
                provider=self._provider,
                model=self._model,
                latency_ms=latency_ms,
            )
        )
        return out

    async def close(self) -> None:
        await self._inner.close()
