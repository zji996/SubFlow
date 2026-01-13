"""Health check routes (LLM)."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from subflow.config import Settings
from subflow.providers import get_llm_provider
from subflow.providers.llm import Message
from subflow.services.llm_health import get_llm_health_monitor

router = APIRouter(tags=["health"])


class LLMProviderHealth(BaseModel):
    status: str  # "ok" | "error" | "unknown"
    provider: str
    model: str
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None
    last_latency_ms: int | None = None
    success_count_1h: int
    error_count_1h: int


class LLMHealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy" | "unknown"
    providers: dict[str, LLMProviderHealth]


def _configured_llm(settings: Settings) -> tuple[str, str, str, str]:
    fast_provider = str(settings.llm_fast.provider or "").strip()
    fast_model = str(settings.llm_fast.model or "").strip()
    power_provider = str(settings.llm_power.provider or "").strip()
    power_model = str(settings.llm_power.model or "").strip()
    return fast_provider, fast_model, power_provider, power_model


@router.get("/health/llm", response_model=LLMHealthResponse)
async def llm_health(request: Request) -> LLMHealthResponse:
    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    fast_provider, fast_model, power_provider, power_model = _configured_llm(settings)
    monitor = get_llm_health_monitor()
    snapshot = await monitor.snapshot(
        fast_provider=fast_provider,
        fast_model=fast_model,
        power_provider=power_provider,
        power_model=power_model,
    )
    return LLMHealthResponse.model_validate(snapshot.to_dict())


async def _probe_profile(settings: Settings, *, profile: str) -> None:
    monitor = get_llm_health_monitor()
    cfg = settings.llm_config_for(profile)
    provider = str(cfg.get("provider") or "").strip() or "unknown"
    model = str(cfg.get("model") or "").strip() or "unknown"

    messages = [
        Message(role="system", content="You are a health check assistant."),
        Message(role="user", content="Reply with exactly one word: OK"),
    ]

    started = time.perf_counter()
    try:
        llm = get_llm_provider(cfg)
    except Exception as exc:
        await monitor.report_error(
            profile=profile,
            provider=provider,
            model=model,
            latency_ms=None,
            error=str(exc),
        )
        return None

    try:
        _ = await asyncio.wait_for(
            llm.complete(messages, temperature=0.0, max_tokens=10),
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        latency_ms = int((time.perf_counter() - started) * 1000)
        await monitor.report_error(
            profile=profile,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            error="timeout",
        )
        return None
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        await monitor.report_error(
            profile=profile,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            error=str(exc),
        )
        return None
    else:
        latency_ms = int((time.perf_counter() - started) * 1000)
        await monitor.report_success(
            profile=profile,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
        )
        return None
    finally:
        try:
            await llm.close()
        except Exception:
            pass


@router.post("/health/llm", response_model=LLMHealthResponse)
async def llm_health_check(request: Request) -> LLMHealthResponse:
    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialized")

    await asyncio.gather(
        _probe_profile(settings, profile="fast"),
        _probe_profile(settings, profile="power"),
    )
    fast_provider, fast_model, power_provider, power_model = _configured_llm(settings)
    snapshot = await get_llm_health_monitor().snapshot(
        fast_provider=fast_provider,
        fast_model=fast_model,
        power_provider=power_provider,
        power_model=power_model,
    )
    return LLMHealthResponse.model_validate(snapshot.to_dict())
