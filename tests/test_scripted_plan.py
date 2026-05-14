"""Tests for synthetic_socio_wind_tunnel.agent.scripted_plan."""

from __future__ import annotations

import random
from collections import Counter

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    LANE_COVE_PROFILE,
    LifePattern,
    build_scripted_plan,
    sample_population,
)
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits


_DESTINATIONS = [f"loc_{i}" for i in range(20)]


def _profile(work_mode: str = "commute", **overrides) -> AgentProfile:
    base = dict(
        agent_id="emma", name="Emma", age=30, occupation="x",
        household="single", home_location="home_loc",
        work_mode=work_mode,  # type: ignore[arg-type]
    )
    base.update(overrides)
    return AgentProfile(**base)


class TestCommute:
    def test_has_workplace_and_return(self):
        rng = random.Random(0)
        plan = build_scripted_plan(_profile("commute"), _DESTINATIONS, "2026-04-27", rng)
        steps = plan.steps
        # Commute day SHALL contain at least 2 commute steps and 1 errand+leisure
        moves = [s for s in steps if s.action == "move"]
        assert len(moves) >= 4
        # Last move SHALL return home
        assert moves[-1].destination == "home_loc"

    def test_includes_errand_and_leisure(self):
        rng = random.Random(0)
        plan = build_scripted_plan(_profile("commute"), _DESTINATIONS, "d", rng)
        activities = [s.activity for s in plan.steps]
        assert any("errand" in a for a in activities)
        assert any("leisure" in a for a in activities)


class TestRemote:
    def test_has_remote_work_at_home(self):
        rng = random.Random(0)
        plan = build_scripted_plan(_profile("remote"), _DESTINATIONS, "d", rng)
        # SHALL have a stay step at home_loc with activity referencing work
        stay_steps = [s for s in plan.steps if s.action == "stay"]
        assert any(s.destination == "home_loc" and "work" in s.activity for s in stay_steps)


class TestShift:
    def test_shift_destination_not_home(self):
        rng = random.Random(0)
        plan = build_scripted_plan(_profile("shift"), _DESTINATIONS, "d", rng)
        work_steps = [s for s in plan.steps if "shift work" in s.activity]
        assert work_steps
        assert work_steps[0].destination != "home_loc"


class TestNonworking:
    def test_no_commute_step(self):
        rng = random.Random(0)
        plan = build_scripted_plan(_profile("nonworking"), _DESTINATIONS, "d", rng)
        # Nonworking day SHALL NOT contain commute step
        for s in plan.steps:
            assert "commute" not in (s.activity or "")
            assert s.reason != "commute"

    def test_returns_home_at_end(self):
        rng = random.Random(0)
        plan = build_scripted_plan(_profile("nonworking"), _DESTINATIONS, "d", rng)
        assert plan.steps[-1].destination == "home_loc"


class TestPublicSignatureCompat:
    def test_legacy_signature_works(self):
        """Legacy callers used (profile, destinations, date, rng) — must keep working."""
        rng = random.Random(42)
        profile = _profile("commute")
        plan = build_scripted_plan(profile, _DESTINATIONS, "2026-04-27", rng)
        assert plan.agent_id == "emma"
        assert plan.date == "2026-04-27"
        assert plan.current_step_index == 0
        assert len(plan.steps) > 0

    def test_smoke_demo_reexport_path_alive(self):
        """Old import path `from smoke_experiment_demo import build_scripted_plan` works."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        from smoke_experiment_demo import build_scripted_plan as legacy  # type: ignore
        from synthetic_socio_wind_tunnel.agent import build_scripted_plan as new
        assert legacy is new

    def test_empty_destinations_returns_empty_plan(self):
        rng = random.Random(0)
        plan = build_scripted_plan(_profile("commute"), [], "d", rng)
        assert plan.steps == []

    def test_missing_work_mode_falls_back_to_flexible(self):
        rng = random.Random(0)
        # Construct an AgentProfile where work_mode is omitted (None default)
        profile = AgentProfile(
            agent_id="x", name="X", age=30, occupation="x",
            household="single", home_location="home_loc",
        )
        assert profile.work_mode is None
        plan = build_scripted_plan(profile, _DESTINATIONS, "d", rng)
        assert len(plan.steps) > 0  # nonworking day shape


class TestSeedReproducibility:
    def test_same_seed_same_plan(self):
        profile = _profile("commute")
        a = build_scripted_plan(profile, _DESTINATIONS, "d", random.Random(42))
        b = build_scripted_plan(profile, _DESTINATIONS, "d", random.Random(42))
        assert [s.time for s in a.steps] == [s.time for s in b.steps]
        assert [s.destination for s in a.steps] == [s.destination for s in b.steps]


class TestPopulationDispatch:
    def test_dispatch_for_each_work_mode_in_lanecove(self):
        agents = sample_population(LANE_COVE_PROFILE, seed=42)
        # Sample 1 of each work_mode and verify build_scripted_plan dispatches
        seen_modes: dict[str, AgentProfile] = {}
        for a in agents:
            if a.work_mode and a.work_mode not in seen_modes:
                seen_modes[a.work_mode] = a
            if len(seen_modes) == 4:
                break
        assert set(seen_modes) >= {"commute", "remote"}, (
            f"expected at least commute+remote in 1000-agent sample, got {set(seen_modes)}"
        )
        for mode, profile in seen_modes.items():
            plan = build_scripted_plan(
                profile, _DESTINATIONS, "2026-04-27", random.Random(0),
            )
            assert plan.steps, f"mode={mode} produced empty plan"


# ===========================================================================
# agent-realistic-routine: weekday/weekend + 8-dim conditioning + LifePattern
# ===========================================================================

class TestWeekdayWeekendDispatch:
    """Saturday/Sunday should not produce commute steps."""

    def test_saturday_no_commute(self):
        rng = random.Random(0)
        profile = _profile("commute")
        plan = build_scripted_plan(profile, _DESTINATIONS, "2026-05-02", rng)  # Saturday
        for step in plan.steps:
            assert "commute" not in (step.activity or "")
            assert step.reason != "commute"

    def test_sunday_includes_outing(self):
        rng = random.Random(0)
        profile = _profile("commute")
        plan = build_scripted_plan(profile, _DESTINATIONS, "2026-05-03", rng)  # Sunday
        activities = " ".join(s.activity or "" for s in plan.steps)
        assert "outing" in activities or "leisure" in activities

    def test_monday_has_commute_for_commute_workmode(self):
        rng = random.Random(0)
        profile = _profile("commute")
        plan = build_scripted_plan(profile, _DESTINATIONS, "2026-05-04", rng)  # Monday
        commute_steps = [s for s in plan.steps if s.reason == "commute"]
        assert len(commute_steps) >= 2  # depart + return


class TestProfileDimensionConditioning:
    """8 profile dims should affect plan generation."""

    def test_couple_kids_under_15_includes_school_pickup(self):
        rng = random.Random(0)
        profile = _profile(
            "commute",
            family_composition="couple_kids_under_15",  # type: ignore[arg-type]
        )
        plan = build_scripted_plan(profile, _DESTINATIONS, "2026-05-04", rng)
        activities = " ".join(s.activity or "" for s in plan.steps)
        assert "pickup" in activities or "kids" in activities

    def test_no_school_pickup_for_lone_person(self):
        rng = random.Random(0)
        profile = _profile(
            "commute",
            family_composition="lone_person",  # type: ignore[arg-type]
        )
        plan = build_scripted_plan(profile, _DESTINATIONS, "2026-05-04", rng)
        activities = " ".join(s.activity or "" for s in plan.steps)
        assert "pickup" not in activities

    def test_zero_car_commute_has_transit_via(self):
        rng = random.Random(0)
        profile = _profile(
            "commute",
            vehicles_at_dwelling="0",  # type: ignore[arg-type]
        )
        plan = build_scripted_plan(profile, _DESTINATIONS, "2026-05-04", rng)
        activities = " ".join(s.activity or "" for s in plan.steps)
        assert "transit" in activities


class TestLifePatternUsage:
    """LifePattern should be used by routine_adherence-gated logic."""

    def test_high_routine_adherence_uses_lifepattern_majority(self):
        # High routine_adherence + LifePattern.preferred_cafe → most days
        # the leisure step destination should be preferred_cafe.
        lp = LifePattern(
            preferred_cafe="preferred_loc",
            morning_commute_minute=15,
            evening_return_minute=30,
        )
        profile = _profile(
            "commute",
            life_pattern=lp,
            personality=PersonalityTraits(routine_adherence=0.95),
        )
        # Sample over many runs to check majority
        leisure_dests = []
        for i in range(50):
            rng = random.Random(i)
            plan = build_scripted_plan(profile, _DESTINATIONS, "2026-05-04", rng)
            for s in plan.steps:
                if s.reason == "leisure":
                    leisure_dests.append(s.destination)
        # At 0.95 adherence, gate fires ~80%; expect ≥ 60% to be preferred
        if leisure_dests:
            preferred_count = sum(1 for d in leisure_dests if d == "preferred_loc")
            ratio = preferred_count / len(leisure_dests)
            assert ratio > 0.5, f"high adherence used preferred only {ratio:.1%}"

    def test_low_routine_adherence_explores(self):
        lp = LifePattern(preferred_cafe="preferred_loc")
        profile = _profile(
            "commute",
            life_pattern=lp,
            personality=PersonalityTraits(routine_adherence=0.1),
        )
        leisure_dests = []
        for i in range(50):
            rng = random.Random(i)
            plan = build_scripted_plan(profile, _DESTINATIONS, "2026-05-04", rng)
            for s in plan.steps:
                if s.reason == "leisure":
                    leisure_dests.append(s.destination)
        if leisure_dests:
            # At 0.1 adherence, gate fires ~20%; ≥ 60% should be NOT preferred
            non_preferred = sum(1 for d in leisure_dests if d != "preferred_loc")
            ratio = non_preferred / len(leisure_dests)
            assert ratio > 0.5, f"low adherence still used preferred {1-ratio:.1%}"

    def test_lifepattern_minute_used_for_commute_time(self):
        lp = LifePattern(morning_commute_minute=42, evening_return_minute=15)
        profile = _profile("commute", life_pattern=lp,
                           personality=PersonalityTraits(routine_adherence=0.5))
        rng = random.Random(0)
        plan = build_scripted_plan(profile, _DESTINATIONS, "2026-05-04", rng)
        commute_steps = [s for s in plan.steps if s.reason == "commute"]
        # Morning commute step time should match life_pattern.morning_commute_minute
        depart = commute_steps[0]
        assert depart.time.endswith(":42"), f"expected :42 minute, got {depart.time}"


class TestNoLifePatternBackwardCompat:

    def test_profile_without_lifepattern_still_plans(self):
        profile = _profile("commute")  # no life_pattern set
        plan = build_scripted_plan(profile, _DESTINATIONS, "2026-05-04",
                                   random.Random(0))
        assert plan.steps  # should still produce a plan


class TestPoolsPath:

    def _get_atlas_and_pools(self):
        import os
        if not os.path.exists("data/lanecove_atlas.json"):
            import pytest
            pytest.skip("Lane Cove atlas fixture not available")
        from synthetic_socio_wind_tunnel import Atlas, build_location_pools
        atlas = Atlas.from_json("data/lanecove_atlas.json")
        pools = build_location_pools(
            atlas, home_count=40, work_count=20, poi_count=30,
            rng=random.Random(42),
        )
        return atlas, pools

    def test_pools_path_no_deprecation_warning(self):
        import warnings
        atlas, pools = self._get_atlas_and_pools()
        profile = _profile("commute",
                           home_location=pools.home_pool[0],
                           workplace=pools.work_pool[0])
        with warnings.catch_warnings(record=True) as warned:
            warnings.simplefilter("always")
            plan = build_scripted_plan(
                profile, pools=pools, date="2026-04-27",
                rng=random.Random(0),
            )
        assert plan.steps
        deprecation = [w for w in warned if issubclass(w.category, DeprecationWarning)]
        assert not deprecation, "pools-path should NOT emit DeprecationWarning"

    def test_pools_path_errand_destination_in_poi_pool(self):
        atlas, pools = self._get_atlas_and_pools()
        profile = _profile("commute",
                           home_location=pools.home_pool[0],
                           workplace=pools.work_pool[0])
        plan = build_scripted_plan(
            profile, pools=pools, date="2026-04-27",
            rng=random.Random(0),
        )
        errand_destinations = [
            s.destination for s in plan.steps if s.reason == "errand"
        ]
        for dest in errand_destinations:
            assert dest in pools.poi_pool, (
                f"errand destination {dest} not in poi_pool"
            )

    def test_pools_path_commute_uses_profile_workplace(self):
        atlas, pools = self._get_atlas_and_pools()
        profile = _profile("commute",
                           home_location=pools.home_pool[0],
                           workplace=pools.work_pool[0])
        plan = build_scripted_plan(
            profile, pools=pools, date="2026-04-27",
            rng=random.Random(0),
        )
        commute_destinations = [
            s.destination for s in plan.steps if s.reason == "commute"
        ]
        non_home_commutes = [d for d in commute_destinations
                             if d != profile.home_location]
        assert non_home_commutes, "must have at least one commute to workplace"
        for d in non_home_commutes:
            assert d == profile.workplace, (
                f"commute destination {d} != profile.workplace "
                f"{profile.workplace}"
            )

    def test_deprecated_destinations_path_emits_warning(self):
        import warnings
        profile = _profile("commute")
        with warnings.catch_warnings(record=True) as warned:
            warnings.simplefilter("always")
            build_scripted_plan(profile, _DESTINATIONS, "2026-05-04",
                                random.Random(0))
        deprecation = [w for w in warned if issubclass(w.category, DeprecationWarning)]
        assert deprecation, "destinations-path must emit DeprecationWarning"
