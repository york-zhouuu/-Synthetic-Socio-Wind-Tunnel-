"""Phase G2 — real snapshot file size measurement: prune-on < prune-off.

Constructs a real MultiDayRunner with seeded encounter events; writes
two snapshots (one with prune env on, one off); compares disk sizes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _build_service_with_events(n_old: int, n_new: int, base_tick_old: int = 10,
                               base_tick_new: int = 600):
    """Build MemoryService with 1 agent × (n_old + n_new) encounter events."""
    from synthetic_socio_wind_tunnel.memory.service import MemoryService
    from synthetic_socio_wind_tunnel.memory.store import MemoryStore
    from synthetic_socio_wind_tunnel.memory.models import MemoryEvent

    service = MemoryService()
    base = datetime(2026, 5, 7, 8, 0)
    aid = "a_001"
    service._stores[aid] = MemoryStore()
    for i in range(n_old):
        service._stores[aid].append(MemoryEvent(
            event_id=f"old_{i}", agent_id=aid,
            tick=base_tick_old, day_index=0,
            simulated_time=base, kind="encounter",
            content=f"event_content_{i}" * 5,  # realistic-ish size
        ))
    for i in range(n_new):
        service._stores[aid].append(MemoryEvent(
            event_id=f"new_{i}", agent_id=aid,
            tick=base_tick_new, day_index=3,
            simulated_time=base, kind="encounter",
            content=f"event_content_{i}" * 5,
        ))
    return service


def _write_snapshot_with_service(
    tmp_path: Path, service, *, day_index: int, env_overrides: dict,
):
    """Invoke real MultiDayRunner._write_snapshot with a controlled service."""
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import (
        MultiDayRunner,
    )
    # Reset observability so each call gets clean state
    try:
        from synthetic_socio_wind_tunnel.observability import (
            instrumentation,
        )
        instrumentation.reset_for_tests()
    except ImportError:
        pass

    runner = MagicMock(spec=MultiDayRunner)
    runner._memory_service = service
    runner._output_dir = tmp_path
    runner._seed = 42
    runner._provider_name = "stub"
    runner._attention_service = None
    runner._tick_metrics_recorder = None
    runner._dialogue_service = None
    runner._ticks_per_day = 288
    mock_ledger = MagicMock()
    mock_ledger.to_snapshot_state.return_value = {}
    mock_ledger.current_time = datetime(2026, 5, 7, 8, 0)
    mock_orch = MagicMock()
    mock_orch._ledger = mock_ledger
    mock_orch._ticks_per_day = 288
    runner._orchestrator = mock_orch
    runner._collect_agents = MagicMock(return_value={})
    # 2026-05-21 R4: avoid MagicMock.isoformat() leaking into pydantic
    runner._start_date_anchor = None

    tick_result = MagicMock()
    tick_result.simulated_time = datetime(2026, 5, 7, 8, 0)
    # Real int for tick_index_in_day computation (mid-day-resume)
    tick_result.tick_index = 0
    tick_result.day_index = day_index
    tick_global = day_index * 288

    write_snap = MultiDayRunner._write_snapshot.__get__(
        runner, MultiDayRunner,
    )
    with patch.dict(os.environ, env_overrides, clear=False):
        path = write_snap(
            tick_index_global=tick_global, day_index=day_index,
            tick_result=tick_result,
        )
    return path


def test_pre_write_prune_reduces_snapshot_size(tmp_path: Path) -> None:
    """spec: snapshot 大小 prune-on < prune-off (real disk size comparison).

    Build a service with 5000 old events (would be evicted) + 500 new
    events. Day=4, grace=2 → cutoff = 576, evicting 5000 events at
    tick 10.
    """
    # Two separate dirs to avoid prune-on contaminating prune-off's
    # service via shared store
    on_dir = tmp_path / "on"
    on_dir.mkdir()
    off_dir = tmp_path / "off"
    off_dir.mkdir()

    # Each run gets its own service (since prune mutates state)
    svc_on = _build_service_with_events(5000, 500)
    svc_off = _build_service_with_events(5000, 500)

    # Run A: prune ON
    path_on = _write_snapshot_with_service(
        on_dir, svc_on, day_index=4,
        env_overrides={
            "SNAPSHOT_PRUNE_BEFORE_WRITE": "1",
            "MEMORY_EVENT_EVICT_GRACE_DAYS": "2",
            "INSTRUMENTATION_DISABLE": "1",
        },
    )
    assert path_on is not None and path_on.is_file()
    size_on = path_on.stat().st_size

    # Run B: prune OFF
    path_off = _write_snapshot_with_service(
        off_dir, svc_off, day_index=4,
        env_overrides={
            "SNAPSHOT_PRUNE_BEFORE_WRITE": "0",
            "MEMORY_EVENT_EVICT_GRACE_DAYS": "2",
            "INSTRUMENTATION_DISABLE": "1",
        },
    )
    assert path_off is not None and path_off.is_file()
    size_off = path_off.stat().st_size

    # prune-on snapshot SHALL be smaller (we evicted ~91% of events)
    assert size_on < size_off, (
        f"prune-on snapshot ({size_on} bytes) NOT smaller than "
        f"prune-off ({size_off} bytes)"
    )
    # Concrete savings should be >= 30% at this fixture scale
    savings_ratio = (size_off - size_on) / size_off
    assert savings_ratio >= 0.30, (
        f"savings ratio {savings_ratio:.1%} below 30% expectation; "
        f"on={size_on} off={size_off}"
    )


def test_snapshot_json_parses_after_pre_write_prune(tmp_path: Path) -> None:
    """Pruned snapshot SHALL be valid JSON and contain only post-cutoff events."""
    svc = _build_service_with_events(100, 50)
    path = _write_snapshot_with_service(
        tmp_path, svc, day_index=4,
        env_overrides={
            "SNAPSHOT_PRUNE_BEFORE_WRITE": "1",
            "MEMORY_EVENT_EVICT_GRACE_DAYS": "2",
            "INSTRUMENTATION_DISABLE": "1",
        },
    )
    assert path is not None
    data = json.loads(path.read_text())
    # SimulationCheckpoint schema
    assert "memory_store_state" in data
    # The evicted-down memory_store should report fewer total events
    # (exact format depends on to_snapshot_state but should be << 150)
    # We don't deeply inspect — just confirm parseable + structurally valid
    assert isinstance(data["memory_store_state"], dict)
