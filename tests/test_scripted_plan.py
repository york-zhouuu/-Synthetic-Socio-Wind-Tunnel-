"""Tests for synthetic_socio_wind_tunnel.agent.scripted_plan."""

from __future__ import annotations

import random
from collections import Counter

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    LANE_COVE_PROFILE,
    build_scripted_plan,
    sample_population,
)


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
