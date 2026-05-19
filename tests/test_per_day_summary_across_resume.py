"""persist-per-day-summaries-across-resumes (2026-05-20) — bug F regression.

Closes thesis-blocking bug where 14-day publishable cells finished via
multiple resumes had `seed_<N>.json` containing only the last spawn's
days. Each test maps 1:1 to a spec scenario in
`openspec/specs/tick-level-resume/spec.md`.

Test design choice: in-process two-runner simulation rather than
subprocess. Reason: the bug is in the MultiDayRunner.run_multi_day
hydrate/write loop, not in subprocess plumbing — testing two runners
that share an output_dir exercises the exact code path the bug lives
in, with 50× faster turnaround. The 8-class testing checklist class 5
(concurrent atomic write) is independently covered by
test_simulation_checkpoint.py.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    AgentRuntime,
)
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import (
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


def _agent(agent_id: str) -> AgentRuntime:
    profile = AgentProfile(
        agent_id=agent_id, name=agent_id, age=30, occupation="x",
        household="single", home_location="a",
    )
    return AgentRuntime(profile=profile, current_location="a")


def _make_orch(start_date: date) -> Orchestrator:
    atlas = _small_atlas()
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())
    agent = _agent("alpha")
    ledger.set_entity(EntityState(
        entity_id=agent.profile.agent_id,
        location_id=agent.current_location,
        position=Coord(x=0.0, y=0.0),
    ))
    return Orchestrator(atlas, ledger, [agent])


# Scenario: each day_end writes its summary atomically
def test_summary_file_written_per_day(tmp_path):
    orch = _make_orch(start_date=date(2026, 4, 22))
    runner = MultiDayRunner(
        orchestrator=orch, seed=42,
        output_dir=tmp_path, provider_name="stub",
    )
    runner.run_multi_day(start_date=date(2026, 4, 22), num_days=3)

    for d in range(3):
        p = tmp_path / f"seed_42_day{d}.summary.json"
        assert p.exists(), f"day {d} summary missing"
        data = json.loads(p.read_text())
        assert data["day_index"] == d


# Scenario: summary files survive cleanup_partials
def test_summary_survives_cleanup_partials(tmp_path):
    orch = _make_orch(start_date=date(2026, 4, 22))
    runner = MultiDayRunner(
        orchestrator=orch, seed=42,
        output_dir=tmp_path, provider_name="stub",
    )
    runner.run_multi_day(start_date=date(2026, 4, 22), num_days=2)

    from synthetic_socio_wind_tunnel.run_resilience import DayCheckpointWriter
    writer = DayCheckpointWriter()
    removed = writer.cleanup_partials(output_dir=tmp_path, seed=42)
    # partials gone
    assert all(".partial.json" in str(p) for p in removed)
    # summaries untouched
    for d in range(2):
        assert (tmp_path / f"seed_42_day{d}.summary.json").exists()


# Scenario: resume from mid-run loads prior day summaries
# (PRIMARY THESIS-CRITICAL REGRESSION)
def test_full_per_day_after_simulated_resume(tmp_path):
    # Spawn 1: run days 0..2, writes 3 .summary.json files
    orch1 = _make_orch(start_date=date(2026, 4, 22))
    r1 = MultiDayRunner(
        orchestrator=orch1, seed=42,
        output_dir=tmp_path, provider_name="stub",
    )
    res1 = r1.run_multi_day(start_date=date(2026, 4, 22), num_days=3)
    assert len(res1.per_day_summaries) == 3
    assert [d.day_index for d in res1.per_day_summaries] == [0, 1, 2]

    # Spawn 2: NEW orchestrator (simulates fresh worker), resume_from=3,
    # runs days 3..4. Without hydration this would only have 2 entries.
    orch2 = _make_orch(start_date=date(2026, 4, 22))
    r2 = MultiDayRunner(
        orchestrator=orch2, seed=42,
        output_dir=tmp_path, provider_name="stub",
        resume_from=3,
    )
    res2 = r2.run_multi_day(start_date=date(2026, 4, 22), num_days=5)

    # THE bug F assertion: per_day_summaries SHALL contain all 5 days
    assert len(res2.per_day_summaries) == 5, (
        f"bug F regression: expected 5 per-day summaries "
        f"(0-4), got {len(res2.per_day_summaries)} "
        f"day_indices={[d.day_index for d in res2.per_day_summaries]}"
    )
    assert [d.day_index for d in res2.per_day_summaries] == [0, 1, 2, 3, 4]


# Scenario: total_encounters reflects all days post-resume
def test_total_metrics_aggregate_across_resumes(tmp_path):
    # Spawn 1
    orch1 = _make_orch(start_date=date(2026, 4, 22))
    r1 = MultiDayRunner(
        orchestrator=orch1, seed=42,
        output_dir=tmp_path, provider_name="stub",
    )
    res1 = r1.run_multi_day(start_date=date(2026, 4, 22), num_days=2)
    spawn1_ticks = res1.total_ticks
    spawn1_enc = res1.total_encounters

    # Spawn 2
    orch2 = _make_orch(start_date=date(2026, 4, 22))
    r2 = MultiDayRunner(
        orchestrator=orch2, seed=42,
        output_dir=tmp_path, provider_name="stub",
        resume_from=2,
    )
    res2 = r2.run_multi_day(start_date=date(2026, 4, 22), num_days=4)

    # total_ticks SHALL be sum of every day's tick_count (4 days total)
    expected_ticks = sum(d.tick_count for d in res2.per_day_summaries)
    assert res2.total_ticks == expected_ticks
    assert res2.total_ticks >= spawn1_ticks
    # encounters: 4-day sum >= 2-day sum (monotone)
    assert res2.total_encounters >= spawn1_enc


# Negative: hydration tolerates malformed summary file (don't crash run)
def test_malformed_summary_file_skipped(tmp_path, caplog):
    import logging

    # write a malformed summary BEFORE run
    bad = tmp_path / "seed_42_day0.summary.json"
    bad.write_text("not valid json")

    orch = _make_orch(start_date=date(2026, 4, 22))
    runner = MultiDayRunner(
        orchestrator=orch, seed=42,
        output_dir=tmp_path, provider_name="stub",
        resume_from=1,  # claim day 0 was done; hydration should try to load
    )
    with caplog.at_level(logging.WARNING):
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=2,
        )
    # Should not crash. Result has day 1 (which was run); day 0 is missing
    # from per_day because the file was unreadable.
    assert len(result.per_day_summaries) == 1
    assert result.per_day_summaries[0].day_index == 1
    # Warning should be in log
    assert any("malformed" in r.message.lower() for r in caplog.records)
