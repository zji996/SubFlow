from __future__ import annotations

import time

import pytest

from subflow.services.llm_health import LLMHealthMonitor


@pytest.mark.asyncio
async def test_llm_health_monitor_success_then_error() -> None:
    monitor = LLMHealthMonitor(redis=None, stale_after_s=3600)
    t0 = time.time()
    t1 = t0 + 0.1

    await monitor.report_success(
        profile="fast",
        provider="openai",
        model="gpt-4o-mini",
        latency_ms=123,
        at_ts=t0,
    )
    fast = await monitor.provider_health(
        profile="fast",
        configured_provider="openai",
        configured_model="gpt-4o-mini",
    )
    assert fast.status == "ok"
    assert fast.last_latency_ms == 123
    assert fast.success_count_1h == 1
    assert fast.error_count_1h == 0

    await monitor.report_error(
        profile="fast",
        provider="openai",
        model="gpt-4o-mini",
        latency_ms=456,
        error="timeout",
        at_ts=t1,
    )
    fast2 = await monitor.provider_health(
        profile="fast",
        configured_provider="openai",
        configured_model="gpt-4o-mini",
    )
    assert fast2.status == "error"
    assert fast2.last_latency_ms == 456
    assert fast2.last_error == "timeout"
    assert fast2.success_count_1h == 1
    assert fast2.error_count_1h == 1


@pytest.mark.asyncio
async def test_llm_health_monitor_stale_becomes_unknown() -> None:
    monitor = LLMHealthMonitor(redis=None, stale_after_s=10)
    now = time.time()
    old = now - 60.0

    await monitor.report_success(
        profile="power",
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        latency_ms=10,
        at_ts=old,
    )
    power = await monitor.provider_health(
        profile="power",
        configured_provider="anthropic",
        configured_model="claude-sonnet-4-20250514",
    )
    assert power.status == "unknown"


@pytest.mark.asyncio
async def test_llm_health_monitor_overall_status() -> None:
    monitor = LLMHealthMonitor(redis=None, stale_after_s=3600)
    t0 = time.time()

    # Unknown when no records
    snap0 = await monitor.snapshot(
        fast_provider="openai",
        fast_model="gpt-4o-mini",
        power_provider="anthropic",
        power_model="claude-sonnet-4-20250514",
    )
    assert snap0.status == "unknown"

    # Degraded: one ok, one unknown
    await monitor.report_success(
        profile="fast",
        provider="openai",
        model="gpt-4o-mini",
        latency_ms=1,
        at_ts=t0,
    )
    snap1 = await monitor.snapshot(
        fast_provider="openai",
        fast_model="gpt-4o-mini",
        power_provider="anthropic",
        power_model="claude-sonnet-4-20250514",
    )
    assert snap1.status == "degraded"

    # Healthy: both ok
    await monitor.report_success(
        profile="power",
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        latency_ms=1,
        at_ts=t0 + 1.0,
    )
    snap2 = await monitor.snapshot(
        fast_provider="openai",
        fast_model="gpt-4o-mini",
        power_provider="anthropic",
        power_model="claude-sonnet-4-20250514",
    )
    assert snap2.status == "healthy"
