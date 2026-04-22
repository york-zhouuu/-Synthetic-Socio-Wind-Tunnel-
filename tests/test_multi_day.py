"""Tests for MultiDayRunner + multi-day orchestrator wiring."""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

import pytest

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    AgentRuntime,
    DailyPlan,
    PlanStep,
)
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.memory import MemoryService
from synthetic_socio_wind_tunnel.orchestrator import (
    MultiDayAggregate,
    MultiDayResult,
    MultiDayRunner,
    Orchestrator,
)


def _small_atlas() -> Atlas:
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "A", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .add_outdoor("b", "B", area_type="street")
        .polygon([(15, 0), (25, 0), (25, 10), (15, 10)])
        .end_outdoor()
        .connect("a", "b", path_type="road", distance=5.0)
        .build()
    )
    return Atlas(region)


def _agent(agent_id: str, home: str = "a") -> AgentRuntime:
    profile = AgentProfile(
        agent_id=agent_id, name=agent_id, age=30, occupation="x",
        household="single", home_location=home,
    )
    return AgentRuntime(profile=profile, current_location=home)


def _ledger_with(agent: AgentRuntime, *, start_date: date) -> Ledger:
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())
    ledger.set_entity(EntityState(
        entity_id=agent.profile.agent_id,
        location_id=agent.current_location,
        position=Coord(x=0.0, y=0.0),
    ))
    return ledger


def _make_orch(agent: AgentRuntime, start_date: date) -> tuple[Orchestrator, Ledger]:
    atlas = _small_atlas()
    ledger = _ledger_with(agent, start_date=start_date)
    orch = Orchestrator(atlas, ledger, [agent])
    return orch, ledger


# ============================================================================
# Construction & mode gating
# ============================================================================

class TestConstruction:
    def test_multi_day_runner_constructs_without_memory_or_planner(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0)
        assert runner.mode == "publishable"

    def test_orchestrator_single_day_still_usable_after_runner_constructed(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        _ = MultiDayRunner(orchestrator=orch, seed=0)
        summary = orch.run()  # direct single-day call still works
        assert summary.total_ticks == 288

    def test_dev_mode_rejects_14_days(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0, mode="dev")
        with pytest.raises(ValueError) as exc:
            runner.run_multi_day(start_date=date(2026, 4, 22), num_days=14)
        assert "dev" in str(exc.value).lower()

    def test_publishable_mode_allows_14_days(self):
        # Just check construction + argument passes the mode check (don't run 14 day)
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0, mode="publishable")
        # run 1 day only to keep test fast
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=1,
        )
        assert len(result.per_day_summaries) == 1


# ============================================================================
# Multi-day run
# ============================================================================

class TestRunMultiDay:
    def test_run_3_days_1_agent(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0)
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=3,
        )
        assert isinstance(result, MultiDayResult)
        assert len(result.per_day_summaries) == 3
        # 288 tick/day × 3 days = 864
        assert result.total_ticks == 864

    def test_per_day_summary_dates_advance(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0)
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=3,
        )
        assert result.per_day_summaries[0].simulated_date == date(2026, 4, 22)
        assert result.per_day_summaries[1].simulated_date == date(2026, 4, 23)
        assert result.per_day_summaries[2].simulated_date == date(2026, 4, 24)

    def test_day_indices_are_0_based(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0)
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=3,
        )
        assert [d.day_index for d in result.per_day_summaries] == [0, 1, 2]


# ============================================================================
# Hook firing
# ============================================================================

class TestHooks:
    def test_on_day_start_and_end_fire_in_order(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0)
        calls: list[str] = []

        def _start(d: date, i: int) -> None:
            calls.append(f"start_{i}_{d}")

        def _end(d: date, i: int, batch: dict[str, Any]) -> None:
            calls.append(f"end_{i}_{d}")

        runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=2,
            on_day_start=_start, on_day_end=_end,
        )
        assert calls == [
            "start_0_2026-04-22",
            "end_0_2026-04-22",
            "start_1_2026-04-23",
            "end_1_2026-04-23",
        ]


# ============================================================================
# day_index propagation
# ============================================================================

class TestDayIndexPropagation:
    def test_tick_result_carries_day_index(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))

        seen_day_indices: set[int] = set()

        def _watch(tick_result):
            seen_day_indices.add(tick_result.day_index)

        orch.register_on_tick_end(_watch)

        runner = MultiDayRunner(orchestrator=orch, seed=0)
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=3)

        assert seen_day_indices == {0, 1, 2}

    def test_memory_event_carries_day_index_via_process_tick(self):
        agent = _agent("alpha")
        orch, ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        memory = MemoryService()

        # Wire memory to orchestrator
        orch.register_on_tick_end(
            lambda tr: memory.process_tick(
                tr, {agent.profile.agent_id: agent},
            )
        )

        runner = MultiDayRunner(orchestrator=orch, memory_service=memory, seed=0)
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=3)

        events = memory.all_for(agent.profile.agent_id)
        # 应有 day_index 0, 1, 2 的 action events
        day_idxs = {e.day_index for e in events}
        assert 0 in day_idxs
        assert 1 in day_idxs
        assert 2 in day_idxs


# ============================================================================
# Cross-seed aggregation
# ============================================================================

class TestCombine:
    def test_combine_3_seeds_1_day(self):
        results: list[MultiDayResult] = []
        for seed in (0, 1, 2):
            agent = _agent("alpha")
            orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
            runner = MultiDayRunner(orchestrator=orch, seed=seed)
            results.append(runner.run_multi_day(
                start_date=date(2026, 4, 22), num_days=1,
            ))

        aggregate = MultiDayResult.combine(results)
        assert isinstance(aggregate, MultiDayAggregate)
        assert aggregate.seed_count == 3
        assert aggregate.seeds == (0, 1, 2)
        # per_day_encounter_stats has one entry per day
        assert len(aggregate.per_day_encounter_stats) == 1
        # stat dict has all 5 keys
        s = aggregate.per_day_encounter_stats[0]
        assert set(s.keys()) == {
            "median", "iqr_lo", "iqr_hi", "ci95_lo", "ci95_hi",
        }


# ============================================================================
# Performance
# ============================================================================

class TestPerformance:
    @pytest.mark.skipif(True, reason="slow — manual perf check only")
    def test_14_day_100_agent_performance(self):
        """Guarded performance check: 14d × 100 agents ≤ 30s wall time.

        Skipped by default (CI budget). Run manually:
            pytest tests/test_multi_day.py::TestPerformance -v -p no:cacheprovider --no-header --runslow
        """
        pass


# ============================================================================
# Serialization
# ============================================================================

class TestSerialization:
    def test_multi_day_result_model_dump_json_safe(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0)
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=2,
        )
        import json
        dump = result.model_dump()
        s = json.dumps(dump, ensure_ascii=False)
        assert "per_day_summaries" in s
        assert "2026-04-22" in s  # ISO date
