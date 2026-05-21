"""parallelize-day-end-llm-batches (2026-05-21): concurrent run_daily_summary.

Per OpenSpec change 'parallelize-day-end-llm-batches'. Refactors
MemoryService.run_daily_summary from serial for loop → asyncio.gather
+ Semaphore(N). Speeds day_end transition ~10-15x.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.memory import MemoryEvent, MemoryService


class StubLLMClient:
    """Test stub that records concurrency + sleeps deterministically."""

    def __init__(self, latency_ms: int = 50, hang_first_n: int = 0):
        self.latency_ms = latency_ms
        self.hang_first_n = hang_first_n
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls_made = 0
        self._lock = asyncio.Lock()

    async def generate(self, prompt: str, *, model: str = "", **kw: Any) -> str:
        async with self._lock:
            self.calls_made += 1
            call_idx = self.calls_made
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if call_idx <= self.hang_first_n:
                await asyncio.sleep(120.0)
            else:
                await asyncio.sleep(self.latency_ms / 1000.0)
            return f"summary for call_{call_idx}"
        finally:
            async with self._lock:
                self.in_flight -= 1


def _make_agents(n: int) -> dict[str, AgentRuntime]:
    return {
        f"a_{i:04d}": AgentRuntime(
            profile=AgentProfile(
                agent_id=f"a_{i:04d}", name=f"Agent{i}", age=30,
                occupation="x", household="single", home_location="loc",
            ),
            current_location="loc",
        )
        for i in range(n)
    }


def _seed_events(svc: MemoryService, agents: dict[str, AgentRuntime],
                 day_index: int = 0) -> None:
    for aid in agents:
        svc.record(aid, MemoryEvent(
            event_id=svc._next_event_id(aid, 12),
            agent_id=aid, tick=12,
            simulated_time=datetime(2026, 4, 22, 1, 0, 0),
            kind="action", content=f"{aid} did x",
            urgency=0.5, importance=0.5, tags=(),
            day_index=day_index,
        ))


def test_concurrent_finishes_faster_than_serial(monkeypatch):
    monkeypatch.setenv("DAILY_SUMMARY_CONCURRENCY", "30")
    agents = _make_agents(100)
    svc = MemoryService(seed=42)
    _seed_events(svc, agents)
    llm = StubLLMClient(latency_ms=100)

    t0 = time.monotonic()
    asyncio.run(svc.run_daily_summary(agents, llm))
    elapsed = time.monotonic() - t0

    assert elapsed < 5.0, (
        f"concurrent finished in {elapsed:.2f}s, expected < 5s "
        f"(serial would be ~10s)"
    )
    assert llm.calls_made == 100
    assert llm.max_in_flight > 1, (
        f"only saw max {llm.max_in_flight} concurrent — not actually parallel"
    )


def test_concurrent_isolates_hang(monkeypatch):
    """1 hang + 99 fast → total ≤ 70s."""
    monkeypatch.setenv("DAILY_SUMMARY_CONCURRENCY", "30")
    agents = _make_agents(100)
    svc = MemoryService(seed=42)
    _seed_events(svc, agents)
    llm = StubLLMClient(latency_ms=50, hang_first_n=1)

    t0 = time.monotonic()
    summaries = asyncio.run(svc.run_daily_summary(agents, llm))
    elapsed = time.monotonic() - t0

    assert elapsed < 70.0, f"hang blocked others — took {elapsed:.1f}s"
    assert len(summaries) == 100
    fallback_count = sum(
        1 for s in summaries.values()
        if "timed out" in s.summary_text or "unavailable" in s.summary_text
    )
    assert fallback_count == 1


def test_semaphore_limits_concurrent_calls(monkeypatch):
    monkeypatch.setenv("DAILY_SUMMARY_CONCURRENCY", "3")
    agents = _make_agents(20)
    svc = MemoryService(seed=42)
    _seed_events(svc, agents)
    llm = StubLLMClient(latency_ms=200)

    asyncio.run(svc.run_daily_summary(agents, llm))

    assert llm.max_in_flight <= 3, (
        f"semaphore violated: max in flight = {llm.max_in_flight}"
    )
    assert llm.calls_made == 20


def test_concurrent_records_daily_summary_event_per_agent(monkeypatch):
    monkeypatch.setenv("DAILY_SUMMARY_CONCURRENCY", "10")
    agents = _make_agents(10)
    svc = MemoryService(seed=42)
    _seed_events(svc, agents)
    llm = StubLLMClient(latency_ms=10)

    asyncio.run(svc.run_daily_summary(agents, llm))

    for aid in agents:
        events = svc.all_for(aid)
        summary_events = [e for e in events if e.kind == "daily_summary"]
        assert len(summary_events) == 1, (
            f"agent {aid}: expected 1 daily_summary event, got {len(summary_events)}"
        )


def test_concurrent_no_events_agent_skipped(monkeypatch):
    monkeypatch.setenv("DAILY_SUMMARY_CONCURRENCY", "10")
    agents = _make_agents(20)
    svc = MemoryService(seed=42)
    half = dict(list(agents.items())[:10])
    _seed_events(svc, half)
    llm = StubLLMClient(latency_ms=10)

    summaries = asyncio.run(svc.run_daily_summary(agents, llm))

    assert llm.calls_made == 10, (
        f"expected 10 LLM calls (only event-bearing agents), got {llm.calls_made}"
    )
    no_event_summaries = [
        s for aid, s in summaries.items() if aid not in half
    ]
    for s in no_event_summaries:
        assert "no events" in s.summary_text


def test_concurrent_preserves_summary_text_from_llm(monkeypatch):
    monkeypatch.setenv("DAILY_SUMMARY_CONCURRENCY", "5")
    agents = _make_agents(5)
    svc = MemoryService(seed=42)
    _seed_events(svc, agents)
    llm = StubLLMClient(latency_ms=10)

    summaries = asyncio.run(svc.run_daily_summary(agents, llm))

    for aid, s in summaries.items():
        assert s.agent_id == aid
        assert s.summary_text.startswith("summary for call_")
