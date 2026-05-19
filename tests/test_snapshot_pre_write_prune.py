"""Phase G1 — pre-write evict triggered correctly by _write_snapshot.

Spec: prune-before-snapshot-write requirement "snapshot 写盘前
cold-prune encounter events".
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def runner_with_mocks(tmp_path, monkeypatch):
    """Build a MultiDayRunner with mocked write_atomic + real
    MemoryService, so we can assert call order."""
    from synthetic_socio_wind_tunnel.memory.service import MemoryService
    from synthetic_socio_wind_tunnel.memory.store import MemoryStore
    from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import (
        MultiDayRunner,
    )

    # Reset observability singleton so each test starts clean
    try:
        from synthetic_socio_wind_tunnel.observability import (
            instrumentation as _inst,
        )
        _inst.reset_for_tests()
    except ImportError:
        pass
    monkeypatch.setenv("INSTRUMENTATION_DISABLE", "1")

    # Build a memory service with 100 encounter events at tick 10,
    # 50 at tick 600 (day 2 if 288/day)
    service = MemoryService()
    base = datetime(2026, 5, 7, 8, 0)
    for aid in ("a_001",):
        if aid not in service._stores:
            service._stores[aid] = MemoryStore()
        for i in range(100):
            service._stores[aid].append(MemoryEvent(
                event_id=f"old_{i}", agent_id=aid,
                tick=10, simulated_time=base, kind="encounter",
                content="x",
            ))
        for i in range(50):
            service._stores[aid].append(MemoryEvent(
                event_id=f"new_{i}", agent_id=aid,
                tick=600, simulated_time=base, kind="encounter",
                content="x",
            ))

    runner = MagicMock(spec=MultiDayRunner)
    runner._memory_service = service
    runner._output_dir = tmp_path
    runner._seed = 42
    runner._provider_name = "stub"
    runner._attention_service = None
    runner._tick_metrics_recorder = None
    runner._dialogue_service = None
    runner._ticks_per_day = 288
    # Mock _orchestrator with a ledger that returns dict for to_snapshot_state
    mock_ledger = MagicMock()
    mock_ledger.to_snapshot_state.return_value = {}
    mock_ledger.current_time = datetime(2026, 5, 7, 8, 0)
    mock_orchestrator = MagicMock()
    mock_orchestrator._ledger = mock_ledger
    runner._orchestrator = mock_orchestrator
    return runner, service


def _call_real_write_snapshot(
    runner_mock, service, *, day_index, tick_index_global,
):
    """Invoke the real MultiDayRunner._write_snapshot logic but with
    mocked write_atomic + agents collection so we can isolate prune."""
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import (
        MultiDayRunner,
    )
    # Mock _collect_agents to return empty (we test memory_store prune)
    runner_mock._collect_agents = MagicMock(return_value={})
    # Use real _write_snapshot bound to mock
    write_snap = MultiDayRunner._write_snapshot.__get__(
        runner_mock, MultiDayRunner,
    )
    tick_result = MagicMock()
    tick_result.simulated_time = datetime(2026, 5, 7, 8, 0)

    # Mock SimulationCheckpoint.write_atomic to capture state
    with patch(
        "synthetic_socio_wind_tunnel.run_resilience.state_snapshot."
        "SimulationCheckpoint.write_atomic"
    ) as mock_write:
        write_snap(
            tick_index_global=tick_index_global,
            day_index=day_index,
            tick_result=tick_result,
        )
    return mock_write


def test_evict_called_before_snapshot_write_at_grace_threshold(
    runner_with_mocks, monkeypatch,
):
    """day_index=4, grace=2 → cutoff = 2*288 = 576. Events at tick=10
    (< 576) SHALL be evicted; events at tick=600 (>= 576) preserved."""
    monkeypatch.setenv("MEMORY_EVENT_EVICT_GRACE_DAYS", "2")
    monkeypatch.delenv("SNAPSHOT_PRUNE_BEFORE_WRITE", raising=False)
    runner, service = runner_with_mocks

    before_total = sum(len(s) for s in service._stores.values())
    assert before_total == 150

    _call_real_write_snapshot(
        runner, service, day_index=4, tick_index_global=4 * 288,
    )

    after_total = sum(len(s) for s in service._stores.values())
    # 100 events at tick 10 were evicted; 50 events at tick 600 remain
    assert after_total == 50, (
        f"expected 50 events after prune, got {after_total}"
    )


def test_evict_skipped_when_day_below_grace(
    runner_with_mocks, monkeypatch,
):
    """day_index=1, grace=2 → cutoff = max(0, 1-2)*288 = 0 → no evict."""
    monkeypatch.setenv("MEMORY_EVENT_EVICT_GRACE_DAYS", "2")
    runner, service = runner_with_mocks

    _call_real_write_snapshot(
        runner, service, day_index=1, tick_index_global=288,
    )

    after_total = sum(len(s) for s in service._stores.values())
    # Nothing evicted because cutoff <= 0
    assert after_total == 150


def test_env_disable_snapshot_prune_skips_evict(
    runner_with_mocks, monkeypatch,
):
    """SNAPSHOT_PRUNE_BEFORE_WRITE=0 → no evict regardless of day."""
    monkeypatch.setenv("MEMORY_EVENT_EVICT_GRACE_DAYS", "2")
    monkeypatch.setenv("SNAPSHOT_PRUNE_BEFORE_WRITE", "0")
    runner, service = runner_with_mocks

    _call_real_write_snapshot(
        runner, service, day_index=10, tick_index_global=10 * 288,
    )

    after_total = sum(len(s) for s in service._stores.values())
    # All preserved
    assert after_total == 150


def test_evict_failure_does_not_block_snapshot_write(
    runner_with_mocks, monkeypatch, caplog,
):
    """If evict raises, snapshot write SHALL still proceed."""
    monkeypatch.setenv("MEMORY_EVENT_EVICT_GRACE_DAYS", "2")
    runner, service = runner_with_mocks

    import logging
    # __slots__ prevents direct attr assignment; use patch.object
    with patch.object(
        type(service),
        "evict_cold_encounter_events_across_agents",
        side_effect=RuntimeError("simulated evict failure"),
    ):
        with caplog.at_level(logging.WARNING):
            mock_write = _call_real_write_snapshot(
                runner, service, day_index=5, tick_index_global=5 * 288,
            )

    # snapshot write SHALL still have been called
    assert mock_write.called, (
        "write_atomic was not called despite evict failure"
    )
    # Warning SHALL have been logged
    warns = [
        r for r in caplog.records
        if "pre-write evict" in r.message.lower()
        or "prune" in r.message.lower()
    ]
    assert len(warns) >= 1
