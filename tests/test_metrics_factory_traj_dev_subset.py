"""Tests for the protag-only `trajectory_deviation_m` and the all-agent
`trajectory_deviation_m_all` sanity column.

Regression for B1 from docs/audit/2026-05-09-bug-hunt.md: original metric
took median across all 100 agents, drowning the 10 protag signal in 90
scripted-agent noise. The new factory returns a tuple
(target_subset_median, all_agent_median).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.metrics.factory import (
    _compute_trajectory_deviation_m,
)
from synthetic_socio_wind_tunnel.metrics.models import DayMetricsSummary


class _FakeArea:
    def __init__(self, x: float, y: float) -> None:
        self.center = Coord(x=x, y=y)


class _FakeAtlas:
    """Minimal atlas with `get_outdoor_area`, `get_building`, `get_center`."""

    def __init__(self, locs: dict[str, _FakeArea]) -> None:
        self._locs = locs

    def get_outdoor_area(self, loc_id: str) -> _FakeArea | None:
        return self._locs.get(loc_id)

    def get_building(self, loc_id: str):  # always None for fake outdoor-only atlas
        return None

    def get_center(self, loc_id: str):
        a = self._locs.get(loc_id)
        return a.center if a else None


def _phase_config() -> dict[str, Any]:
    return {"baseline_days": 1, "intervention_days": 1, "post_days": 1}


def _per_day(end_locations_day1: dict[str, str]) -> list[DayMetricsSummary]:
    return [
        DayMetricsSummary(day_index=0),
        DayMetricsSummary(
            day_index=1, end_of_day_location_by_agent=end_locations_day1,
        ),
        DayMetricsSummary(day_index=2),
    ]


def _build_atlas() -> _FakeAtlas:
    return _FakeAtlas({
        "target": _FakeArea(0.0, 0.0),
        "near": _FakeArea(10.0, 0.0),
        "far": _FakeArea(1000.0, 0.0),
    })


class TestComputeTrajectoryDeviationSubset:
    """The 10-protag-vs-90-scripted dilution scenario the bug audit found."""

    def test_protag_only_vs_all_diverge(self):
        # 10 protag end at "near" (10m from target); 90 scripted at "far" (1000m).
        end = {f"protag_{i}": "near" for i in range(10)}
        end.update({f"scripted_{i}": "far" for i in range(90)})

        target_ids = {f"protag_{i}" for i in range(10)}
        meta = {"target_location": "target", "target_agent_ids": tuple(target_ids)}

        subset, all_ = _compute_trajectory_deviation_m(
            _per_day(end),
            atlas=_build_atlas(),
            variant_name="hyperlocal_push",
            variant_metadata=meta,
            phase_config=_phase_config(),
        )
        assert subset == pytest.approx(10.0, abs=1e-6), \
            "protag-only median SHALL reflect the 10 protag at 'near'"
        assert all_ == pytest.approx(1000.0, abs=1e-6), \
            "all-agent median SHALL be dominated by 90 scripted at 'far'"
        assert subset != all_, \
            "subset and all medians SHALL diverge when protag != population"

    def test_protag_fallback_when_metadata_missing_target_ids(self):
        # No target_agent_ids in metadata, but protag_ids passed as fallback.
        end = {f"protag_{i}": "near" for i in range(5)}
        end.update({f"other_{i}": "far" for i in range(20)})

        meta = {"target_location": "target"}  # NO target_agent_ids
        protag_fallback = {f"protag_{i}" for i in range(5)}

        subset, all_ = _compute_trajectory_deviation_m(
            _per_day(end),
            atlas=_build_atlas(),
            variant_name="hyperlocal_push",
            variant_metadata=meta,
            phase_config=_phase_config(),
            protag_ids=protag_fallback,
        )
        assert subset == pytest.approx(10.0, abs=1e-6)
        # all_ median = 22.5th-percentile across 25 entries; with 5 near-vals + 20 far,
        # median lands at 'far' (1000.0) since the 13th entry (0-indexed 12) is far.
        assert all_ == pytest.approx(1000.0, abs=1e-6)

    def test_subset_none_when_no_target_ids_and_no_fallback(self):
        end = {f"a{i}": "near" for i in range(10)}
        meta = {"target_location": "target"}
        subset, all_ = _compute_trajectory_deviation_m(
            _per_day(end),
            atlas=_build_atlas(),
            variant_name="hyperlocal_push",
            variant_metadata=meta,
            phase_config=_phase_config(),
            protag_ids=None,
        )
        assert subset is None
        assert all_ == pytest.approx(10.0, abs=1e-6)

    def test_baseline_returns_none_for_both(self):
        end = {f"a{i}": "near" for i in range(10)}
        subset, all_ = _compute_trajectory_deviation_m(
            _per_day(end),
            atlas=_build_atlas(),
            variant_name="baseline",
            variant_metadata={"name": "baseline"},
            phase_config=_phase_config(),
        )
        assert subset is None
        assert all_ is None

    def test_phone_friction_returns_none(self):
        end = {f"a{i}": "near" for i in range(10)}
        subset, all_ = _compute_trajectory_deviation_m(
            _per_day(end),
            atlas=_build_atlas(),
            variant_name="phone_friction",
            variant_metadata={"target_location": "target"},
            phase_config=_phase_config(),
        )
        assert subset is None
        assert all_ is None

    def test_no_atlas_returns_none(self):
        end = {f"a{i}": "near" for i in range(10)}
        subset, all_ = _compute_trajectory_deviation_m(
            _per_day(end),
            atlas=None,
            variant_name="hyperlocal_push",
            variant_metadata={"target_location": "target",
                              "target_agent_ids": tuple(end.keys())},
            phase_config=_phase_config(),
        )
        assert subset is None
        assert all_ is None


class TestRunMetricsFactoryWiresBothFields:

    def test_run_metrics_has_traj_dev_m_and_all(self):
        from synthetic_socio_wind_tunnel.ledger import Ledger
        from synthetic_socio_wind_tunnel.metrics.factory import build_run_metrics
        from synthetic_socio_wind_tunnel.metrics.recorder import (
            TickMetricsRecorder,
        )
        from synthetic_socio_wind_tunnel.orchestrator.models import TickResult
        from datetime import datetime

        led = Ledger()
        led.current_time = datetime(2026, 5, 8)
        rec = TickMetricsRecorder(ledger=led)

        # Push two day-roll snapshots so per_day has at least intervention_end.
        # We don't need real positions because atlas is None → both fields stay None.
        rec.on_tick_end(TickResult(
            tick_index=0, day_index=0, simulated_time=datetime(2026, 5, 8),
            commits=(), encounter_candidates=(),
        ))

        mdr = MagicMock()
        mdr.seed = 42
        rm = build_run_metrics(
            rec, multi_day_result=mdr,
            variant_name="baseline",
            variant_metadata={"name": "baseline"},
            phase_config=_phase_config(),
        )
        # Both fields exist on the model.
        assert hasattr(rm, "trajectory_deviation_m")
        assert hasattr(rm, "trajectory_deviation_m_all")
        assert rm.trajectory_deviation_m is None
        assert rm.trajectory_deviation_m_all is None
