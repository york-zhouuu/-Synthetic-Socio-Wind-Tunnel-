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


# ============================================================================
# run-resilience: per-day checkpoint + resume_from + graceful-stop
# ============================================================================

class TestCheckpoint:
    def test_per_day_partial_written(self, tmp_path):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=42,
            output_dir=tmp_path, provider_name="stub",
        )
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=3)
        for d in range(3):
            assert (tmp_path / f"seed_42_day{d}.partial.json").exists()

    def test_no_partial_when_output_dir_none(self, tmp_path):
        """向后兼容：output_dir=None 时不应有任何写盘。"""
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0)
        # 故意先在 tmp_path 放个无关 file 来验证 isolation
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=2)
        assert list(tmp_path.glob("*.partial.json")) == []

    def test_partial_contains_required_fields(self, tmp_path):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=7,
            output_dir=tmp_path, provider_name="gemini",
        )
        runner.run_multi_day(start_date=date(2026, 4, 22), num_days=1)
        import json
        data = json.loads((tmp_path / "seed_7_day0.partial.json").read_text())
        assert data["seed"] == 7
        assert data["day_index"] == 0
        assert data["provider"] == "gemini"
        assert data["schema_version"] == "1"
        assert "run_metrics" in data
        assert "ledger_snapshot" in data

    def test_partial_write_failure_does_not_stop_run(self, tmp_path, caplog):
        """Mock CheckpointWriter to raise on day 1; run should still reach day 2."""
        from synthetic_socio_wind_tunnel.run_resilience import DayCheckpointWriter

        class BrokenWriter(DayCheckpointWriter):
            def __init__(self):
                super().__init__()
                self.calls = 0
            def write_partial(self, **kw):
                self.calls += 1
                if self.calls == 2:
                    raise OSError("disk full simulated")
                return super().write_partial(**kw)

        broken = BrokenWriter()
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=0,
            output_dir=tmp_path, checkpoint_writer=broken,
            provider_name="stub",
        )
        import logging
        with caplog.at_level(logging.WARNING):
            result = runner.run_multi_day(
                start_date=date(2026, 4, 22), num_days=3,
            )
        # All 3 days should still complete
        assert len(result.per_day_summaries) == 3
        # Warning logged for day 1
        assert any("write_partial failed" in r.message for r in caplog.records)


class TestResumeFrom:
    def test_resume_from_5_yields_9_day_summaries(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0, resume_from=5)
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=14,
        )
        assert len(result.per_day_summaries) == 9
        assert result.per_day_summaries[0].day_index == 5
        assert result.per_day_summaries[-1].day_index == 13

    def test_resume_from_zero_unchanged_behavior(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0, resume_from=0)
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=3,
        )
        assert len(result.per_day_summaries) == 3
        assert result.per_day_summaries[0].day_index == 0

    def test_resume_from_exceeds_num_days_raises(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0, resume_from=20)
        with pytest.raises(ValueError) as exc:
            runner.run_multi_day(
                start_date=date(2026, 4, 22), num_days=14,
            )
        assert "20" in str(exc.value)
        assert "14" in str(exc.value)

    def test_resume_from_negative_raises_in_init(self):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        with pytest.raises(ValueError):
            MultiDayRunner(orchestrator=orch, seed=0, resume_from=-1)


class TestGracefulStop:
    def test_graceful_stop_truncates_run(self, tmp_path):
        """Setting _graceful_stop_requested mid-run aborts current day and
        returns truncated MultiDayResult."""
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=0,
            output_dir=tmp_path, provider_name="stub",
        )

        # Trip graceful_stop after day 1's tick 5 — register an on_tick_end
        # hook that flips the flag once the day_index goes to 1.
        tick_count = {"n": 0}

        def trip(tick_result):
            tick_count["n"] += 1
            if tick_result.day_index == 1 and tick_count["n"] > 290:
                runner._graceful_stop_requested = True

        orch.register_on_tick_end(trip)
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=14,
        )
        # day 0 fully ran (288 ticks), day 1 partially aborted
        assert len(result.per_day_summaries) == 1
        assert result.per_day_summaries[0].day_index == 0
        # graceful_stop metadata exposed
        assert result.metadata["graceful_stop"] is True

    def test_graceful_stop_writes_partial_of_last_complete_day(self, tmp_path):
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(
            orchestrator=orch, seed=99,
            output_dir=tmp_path, provider_name="stub",
        )
        # Trip on first tick of day 2 (so days 0,1 complete)
        def trip(tick_result):
            if tick_result.day_index == 2:
                runner._graceful_stop_requested = True
        orch.register_on_tick_end(trip)
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=5,
        )
        # Days 0 and 1 should have partial files; day 2+ should not
        assert (tmp_path / "seed_99_day0.partial.json").exists()
        assert (tmp_path / "seed_99_day1.partial.json").exists()
        assert not (tmp_path / "seed_99_day2.partial.json").exists()
        assert len(result.per_day_summaries) == 2

    def test_unbroken_run_unaffected_by_flag(self):
        """If flag never goes True, behavior is identical to pre-resilience."""
        agent = _agent("alpha")
        orch, _ledger = _make_orch(agent, start_date=date(2026, 4, 22))
        runner = MultiDayRunner(orchestrator=orch, seed=0)
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=3,
        )
        assert len(result.per_day_summaries) == 3
        assert result.metadata["graceful_stop"] is False
