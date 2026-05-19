"""Layer 6 fault injection: instrumentation must not crash run on
psutil / gc / service iteration failures.

Spec scenario "psutil 调用失败时 run 不 crash" + similar coverage for
each independent metric in `_collect_day_end_observability`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayRunner


def _make_minimal_runner() -> MultiDayRunner:
    """Construct a bare MultiDayRunner instance for testing the
    observability helper method in isolation."""
    runner = MultiDayRunner.__new__(MultiDayRunner)
    runner._memory_service = None
    runner._dialogue_service = None
    runner._day_tick_latencies_ms = []
    return runner


@pytest.mark.parametrize("exception_cls", [
    OSError,
    PermissionError,
    Exception,  # broad catch — defensive
])
def test_psutil_memory_info_failure_falls_back(exception_cls) -> None:
    """psutil.Process().memory_info() raises → out["rss_mb"]==0.0, no propagation."""
    runner = _make_minimal_runner()
    with patch("psutil.Process") as MockProc:
        instance = MockProc.return_value
        instance.memory_info.side_effect = exception_cls("simulated fault")
        out = runner._collect_day_end_observability(
            agents_by_id={}, day_tick_latencies_ms=[],
        )
    assert out["rss_mb"] == 0.0
    assert out["vms_mb"] == 0.0


def test_gc_get_count_failure_falls_back() -> None:
    runner = _make_minimal_runner()
    with patch(
        "synthetic_socio_wind_tunnel.orchestrator.multi_day.gc.get_count",
        side_effect=RuntimeError("gc disabled"),
    ):
        out = runner._collect_day_end_observability(
            agents_by_id={}, day_tick_latencies_ms=[],
        )
    assert out["gc_collections"] == (0, 0, 0)


def test_memory_store_iteration_failure_falls_back() -> None:
    runner = _make_minimal_runner()
    # Plant a memory_service whose `_stores` is a property that raises
    bad_service = MagicMock()
    bad_service._stores = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    runner._memory_service = bad_service
    out = runner._collect_day_end_observability(
        agents_by_id={}, day_tick_latencies_ms=[],
    )
    # Falls back without crashing
    assert isinstance(out["memory_store_event_count"], int)
    assert out["memory_store_event_count"] >= 0


def test_dialogue_count_failure_falls_back() -> None:
    runner = _make_minimal_runner()
    bad_service = MagicMock()
    # __len__ raise
    bad_service._dialogues = MagicMock()
    type(bad_service._dialogues).__len__ = MagicMock(
        side_effect=RuntimeError("dialogues broken"),
    )
    runner._dialogue_service = bad_service
    out = runner._collect_day_end_observability(
        agents_by_id={}, day_tick_latencies_ms=[],
    )
    assert out["dialogue_count"] == 0


def test_empty_latency_list_yields_zero_quantiles() -> None:
    """No tick samples (e.g., observability disabled mid-day) → quantile
    fields default 0, no crash."""
    runner = _make_minimal_runner()
    out = runner._collect_day_end_observability(
        agents_by_id={}, day_tick_latencies_ms=[],
    )
    assert out["tick_latency_ms_p50"] == 0.0
    assert out["tick_latency_ms_p95"] == 0.0
    assert out["tick_latency_ms_max"] == 0.0


def test_single_sample_latency_does_not_crash() -> None:
    """Only 1 latency sample (n<2 quantile edge case) → falls back to
    using sample itself for p50/p95, max from list."""
    runner = _make_minimal_runner()
    out = runner._collect_day_end_observability(
        agents_by_id={}, day_tick_latencies_ms=[42.5],
    )
    assert out["tick_latency_ms_p50"] == 42.5
    assert out["tick_latency_ms_p95"] == 42.5
    assert out["tick_latency_ms_max"] == 42.5


def test_normal_path_collects_all_metrics() -> None:
    """When everything works, out dict has all 8 keys populated reasonably."""
    runner = _make_minimal_runner()
    latencies = [5.0, 6.0, 4.0, 100.0, 8.0]  # one tail outlier
    out = runner._collect_day_end_observability(
        agents_by_id={}, day_tick_latencies_ms=latencies,
    )
    # psutil call should succeed in this test process
    assert out["rss_mb"] > 0  # we're a real Python process
    assert out["vms_mb"] > 0
    assert len(out["gc_collections"]) == 3
    # latency stats
    assert out["tick_latency_ms_max"] == 100.0
    # p50 should be around the median (5.0 or 6.0)
    assert 4.0 <= out["tick_latency_ms_p50"] <= 8.0
    # p95 should reflect the outlier
    assert out["tick_latency_ms_p95"] > out["tick_latency_ms_p50"]
