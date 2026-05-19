"""Layer 3 — performance budget: fast path SHALL be ≥ 5× legacy on N=10000.

Hand-built MemoryEvent batch (no orchestrator runtime), median of 3
trials. Marked @slow because each trial is ~0.5-2 seconds.

If ratio fast/legacy > 0.2 → fail with both timings + ratio + which
implementation chosen (A asdict / B typed / etc.).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
from synthetic_socio_wind_tunnel.memory import service as _svc


N_EVENTS = 10_000
N_TRIALS = 3
RATIO_BUDGET = 0.20  # fast must be ≤ 20% of legacy time (= 5× speedup)


def _build_events(n: int) -> list[MemoryEvent]:
    """N realistic-ish MemoryEvent objects with varied fields."""
    base = datetime(2026, 4, 22, 8, 0, 0)
    events = []
    for i in range(n):
        kind = ("encounter", "action", "reflection", "conversation",
                "daily_summary", "life_history")[i % 6]
        events.append(MemoryEvent(
            event_id=f"ev_{i:08d}",
            agent_id=f"a_{i % 1000:04d}",
            tick=i,
            simulated_time=base + timedelta(minutes=i),
            kind=kind,  # type: ignore[arg-type]
            content=f"event content #{i}",
            actor_id=f"a_{(i + 1) % 1000:04d}" if i % 3 == 0 else None,
            location_id=f"loc_{i % 100:03d}" if i % 2 == 0 else None,
            day_index=i // 288,
            importance=(i % 100) / 100.0,
            participants=(f"a_{(i + 2) % 1000:04d}",) if i % 4 == 0 else (),
            tags=("tag1", "tag2") if i % 5 == 0 else (),
            embedding=tuple([0.1] * 128) if i % 50 == 0 else None,
            related_memory_ids=(f"ev_{(i - 1):08d}",) if i > 0 and i % 7 == 0 else (),
        ))
    return events


def _time_serialize(impl, events: list[MemoryEvent]) -> float:
    """Return wall-clock seconds for serializing all events with impl."""
    t0 = time.perf_counter()
    _ = [impl(ev) for ev in events]
    return time.perf_counter() - t0


@pytest.mark.slow
@pytest.mark.xfail(
    reason=(
        "2026-05-19: accelerate-memory-snapshot-serialization "
        "was reverted — 5× speedup target was refuted empirically "
        "(work is Python-level irreducible; measured ~3.5×). The "
        "follow-on enforce-worker-rss-cap change addresses the "
        "root cause (cut event count, return arena pages) instead. "
        "Test kept as historical record / future revisit budget."
    ),
    strict=False,
)
def test_fast_path_5x_speedup_over_legacy() -> None:
    """harden-worker-resilience principle: data-driven optimization.
    Budget for accelerate-memory-snapshot-serialization spec.
    """
    legacy = getattr(_svc, "_event_to_json_legacy", None)
    fast = getattr(_svc, "_event_to_json_fast", None)
    if legacy is None or fast is None:
        pytest.fail(
            "G4 not landed yet — _event_to_json_legacy / _event_to_json_fast "
            "must exist before this test can run. (See "
            "openspec/changes/accelerate-memory-snapshot-serialization/tasks.md "
            "group 4.)"
        )

    events = _build_events(N_EVENTS)

    # warm up (JIT / branch predictor / etc.)
    _time_serialize(legacy, events[:100])
    _time_serialize(fast, events[:100])

    legacy_times = [_time_serialize(legacy, events) for _ in range(N_TRIALS)]
    fast_times = [_time_serialize(fast, events) for _ in range(N_TRIALS)]

    legacy_sorted = sorted(legacy_times)
    fast_sorted = sorted(fast_times)
    legacy_med = legacy_sorted[len(legacy_sorted) // 2]
    fast_med = fast_sorted[len(fast_sorted) // 2]

    ratio = fast_med / legacy_med

    assert ratio <= RATIO_BUDGET, (
        f"\n========== performance budget violated =========="
        f"\n  N events:    {N_EVENTS:,}"
        f"\n  legacy:      {[round(t*1000, 1) for t in legacy_sorted]} ms (median {legacy_med*1000:.1f})"
        f"\n  fast:        {[round(t*1000, 1) for t in fast_sorted]} ms (median {fast_med*1000:.1f})"
        f"\n  ratio:       {ratio:.3f}× (budget {RATIO_BUDGET:.2f}×)"
        f"\n  speedup:     {1/ratio:.1f}× (need ≥ 5×)"
    )

    # Stash result for human eyes
    print(
        f"\nfast_path speedup: {1/ratio:.1f}× "
        f"(legacy {legacy_med*1000:.0f}ms → fast {fast_med*1000:.0f}ms)"
    )
