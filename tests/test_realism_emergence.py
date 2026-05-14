"""
Group emergence regression tests for agent-realistic-routine.

These tests assert that the new scripted_plan produces realistic temporal
+ routine patterns. They run a small mini-sim (50 agents × 7 days) and
check rush-hour shape, weekday/weekend differential, and routine stickiness.

NOTE: These tests run an actual sim and take ~10-20s. Mark `slow` if needed.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.agent import (
    AgentRuntime,
    LANE_COVE_PROFILE,
    build_scripted_plan,
    sample_population,
)
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.lanecove import (
    ATLAS_CACHE_PATH,
    create_atlas_from_osm,
)
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import MultiDayRunner, Orchestrator


pytestmark = pytest.mark.skipif(
    not ATLAS_CACHE_PATH.exists(),
    reason="atlas cache not built; run cartography first",
)


@pytest.fixture(scope="module")
def mini_sim_metrics():
    """Run a 50-agent × 7-day baseline once; return aggregated metrics."""
    atlas = create_atlas_from_osm()
    rng = random.Random(42)
    all_dests = list(atlas._region.outdoor_areas.keys())[:30]
    template = LANE_COVE_PROFILE.model_copy(update={"size": 50})
    profiles = sample_population(template, seed=42, home_locations=tuple(all_dests))

    ledger = Ledger()
    start_date = date(2026, 5, 4)  # Monday
    ledger.current_time = datetime.combine(start_date, datetime.min.time())

    runtimes = []
    for p in profiles:
        home = p.home_location
        ledger.set_entity(EntityState(
            entity_id=p.agent_id,
            position=Coord(x=0, y=0),
            location_id=home,
        ))
        rt = AgentRuntime(profile=p, current_location=home)
        rt.plan = build_scripted_plan(p, all_dests, start_date.isoformat(), rng)
        runtimes.append(rt)

    orch = Orchestrator(atlas, ledger, runtimes, tick_minutes=5, seed=42)
    runner = MultiDayRunner(orchestrator=orch)

    hourly_encs = [0] * 24
    agent_visits = defaultdict(list)

    def hook(tr):
        if tr.simulated_time is not None:
            hourly_encs[tr.simulated_time.hour] += len(tr.encounter_candidates)
    orch.register_on_tick_end(hook)

    def on_day_start(current_date, day_index):
        rng_day = random.Random(42 + day_index)
        if day_index > 0:
            for rt in runtimes:
                if rt.plan and rt.plan.steps:
                    visited = {s.destination for s in rt.plan.steps if s.destination}
                    agent_visits[rt.profile.agent_id].append(visited)
        for rt in runtimes:
            home = rt.profile.home_location
            ledger.set_entity(EntityState(
                entity_id=rt.profile.agent_id,
                position=Coord(x=0, y=0),
                location_id=home,
            ))
            rt.current_location = home
            rt.cancel_movement()
            rt.plan = build_scripted_plan(
                rt.profile, all_dests, current_date.isoformat(), rng_day,
            )

    result = runner.run_multi_day(start_date=start_date, num_days=7,
                                  on_day_start=on_day_start)

    # Capture final day
    for rt in runtimes:
        if rt.plan and rt.plan.steps:
            visited = {s.destination for s in rt.plan.steps if s.destination}
            agent_visits[rt.profile.agent_id].append(visited)

    return {
        "hourly_encs": hourly_encs,
        "agent_visits": dict(agent_visits),
        "per_day": [s.encounter_count for s in result.per_day_summaries],
        "profiles": profiles,
        "start_date": start_date,
    }


class TestF1TemporalRealism:

    def test_daytime_peak_above_lunch_dip(self, mini_sim_metrics):
        # Threshold re-calibrated 2026-05-10 (fix-encounter-detection-and-observability):
        # B9 fix added stationary co-presence to encounter detection, which
        # flattens the lunch-time dip (people dwelling at cafe lunch are now
        # counted, not just transit). 1.5× → 1.15× reflects the post-fix
        # realism baseline; the temporal signal is still present, just gentler.
        h = mini_sim_metrics["hourly_encs"]
        peak = max(h[9:20])
        dip = min(h[12:14])
        ratio = peak / max(1, dip)
        assert ratio > 1.15, f"daytime peak / lunch dip ratio {ratio:.2f} <= 1.15"

    def test_weekday_total_differs_from_weekend(self, mini_sim_metrics):
        # Threshold re-calibrated 2026-05-10 (fix-encounter-detection-and-observability):
        # B9 fix dominated total encounters with dwell co-presence which is
        # similar across weekday/weekend; the scripted-plan delta still shows
        # but at smaller magnitude. 15% → 4% reflects post-fix baseline.
        per_day = mini_sim_metrics["per_day"]
        start = mini_sim_metrics["start_date"]
        weekday_totals = []
        weekend_totals = []
        from datetime import timedelta
        for i, total in enumerate(per_day):
            d = start + timedelta(days=i)
            (weekday_totals if d.weekday() < 5 else weekend_totals).append(total)
        if not (weekday_totals and weekend_totals):
            pytest.skip("need both weekday + weekend days")
        wd_avg = sum(weekday_totals) / len(weekday_totals)
        we_avg = sum(weekend_totals) / len(weekend_totals)
        diff = abs(wd_avg - we_avg) / max(1, wd_avg)
        assert diff > 0.04, f"weekday/weekend diff {diff:.1%} <= 4%"


class TestF3RoutineStickiness:

    def test_high_adherence_agents_repeat_venue(self, mini_sim_metrics):
        agent_visits = mini_sim_metrics["agent_visits"]
        profiles = mini_sim_metrics["profiles"]
        profile_by_id = {p.agent_id: p for p in profiles}

        repeat_pcts = []
        for aid, day_visits in agent_visits.items():
            if len(day_visits) < 2:
                continue
            p = profile_by_id[aid]
            if p.personality.routine_adherence <= 0.7:
                continue
            home = p.home_location
            venue_day = defaultdict(int)
            for ds in day_visits:
                for v in ds:
                    if v and v != home:
                        venue_day[v] += 1
            if not venue_day:
                continue
            repeat_pcts.append(max(venue_day.values()) / len(day_visits))
        if len(repeat_pcts) < 5:
            pytest.skip("not enough high-adherence agents in sample")
        from statistics import median
        m = median(repeat_pcts)
        assert m > 0.55, f"median high-adherence repeat {m:.1%} <= 55%"

    def test_low_adherence_agents_more_diverse(self, mini_sim_metrics):
        agent_visits = mini_sim_metrics["agent_visits"]
        profiles = mini_sim_metrics["profiles"]
        profile_by_id = {p.agent_id: p for p in profiles}

        repeat_pcts = []
        for aid, day_visits in agent_visits.items():
            if len(day_visits) < 2:
                continue
            p = profile_by_id[aid]
            if p.personality.routine_adherence >= 0.4:
                continue
            home = p.home_location
            venue_day = defaultdict(int)
            for ds in day_visits:
                for v in ds:
                    if v and v != home:
                        venue_day[v] += 1
            if not venue_day:
                continue
            repeat_pcts.append(max(venue_day.values()) / len(day_visits))
        if len(repeat_pcts) < 5:
            pytest.skip("not enough low-adherence agents")
        from statistics import median
        m = median(repeat_pcts)
        assert m < 0.85, f"low-adherence repeat {m:.1%} too high"

    def test_high_vs_low_adherence_differential(self, mini_sim_metrics):
        """High-adherence repeat should exceed low-adherence repeat."""
        agent_visits = mini_sim_metrics["agent_visits"]
        profiles = mini_sim_metrics["profiles"]
        profile_by_id = {p.agent_id: p for p in profiles}

        high = []
        low = []
        for aid, day_visits in agent_visits.items():
            if len(day_visits) < 2:
                continue
            p = profile_by_id[aid]
            home = p.home_location
            venue_day = defaultdict(int)
            for ds in day_visits:
                for v in ds:
                    if v and v != home:
                        venue_day[v] += 1
            if not venue_day:
                continue
            r = max(venue_day.values()) / len(day_visits)
            if p.personality.routine_adherence > 0.7:
                high.append(r)
            elif p.personality.routine_adherence < 0.4:
                low.append(r)
        if not (high and low):
            pytest.skip("need both adherence groups")
        from statistics import median
        assert median(high) > median(low), (
            f"high adherence median {median(high):.2f} not > low {median(low):.2f}"
        )
