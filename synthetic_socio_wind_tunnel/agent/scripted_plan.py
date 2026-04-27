"""
Scripted plan generation for non-protagonist (Haiku-tier) agents.

Used when the simulation budget can't afford LLM calls per agent per day.
Day shape branches on `profile.work_mode`:

- commute    → home → workplace → errand → home (with ABS Travel Survey
                 departure-time anchors)
- remote     → home morning + 1-2 leisure/errand outings + home
- shift      → split-shift work + 1 errand
- nonworking → flexible day with 2-3 errand/leisure trips

Public API: `build_scripted_plan(profile, destinations, date, rng) -> DailyPlan`
matches the legacy signature from `tools/smoke_experiment_demo.py`; existing
callers continue to work after import-path migration.

Behavioral calibration target (`agent-calibration` change Part V):
- Step time anchors approximate ABS Travel Survey 2021 Sydney departure-time
  distribution.
- Errand/leisure destinations should be picked weighted by Popular Times
  hourly intensity once that data ships.

This module ships with **uniform-random destination selection**; once
`data/calibration/lanecove_popular_times.json` exists,
`_pick_destination_with_popularity` is the seam where weighting plugs in.
"""

from __future__ import annotations

import random

from .planner import DailyPlan, PlanStep
from .profile import AgentProfile, WorkMode


# ABS Travel Survey 2021 (Sydney) journey-to-work departure-time peaks.
# These are placeholder anchors; once ABS JSON ships, they should be sampled
# from the empirical distribution. (calibration design D3)
_COMMUTE_DEPART_AM_PEAKS = ("7:30", "7:45", "8:00", "8:15", "8:30", "9:00")
_COMMUTE_RETURN_PM_PEAKS = ("17:00", "17:30", "18:00", "18:30", "19:00")
_ERRAND_HOURS = (10, 11, 14, 15, 16)
_LEISURE_HOURS = (10, 11, 17, 18, 19, 20)


def _pick_destination(
    rng: random.Random,
    destinations: list[str],
    *,
    exclude: str | None = None,
) -> str:
    """
    Pick a destination uniformly at random, optionally excluding one.

    Seam for Popular-Times-weighted picking once that data is wired in
    (`agent-calibration` Section 4.4).
    """
    pool = [d for d in destinations if d != exclude] if exclude else destinations
    if not pool:
        return destinations[0] if destinations else "home"
    return rng.choice(pool)


def _step(time: str, action: str, destination: str | None, *,
          duration: int, activity: str, social: str = "alone",
          reason: str = "") -> PlanStep:
    return PlanStep(
        time=time, action=action, destination=destination,
        duration_minutes=duration, activity=activity,
        social_intent=social,  # type: ignore[arg-type]
        reason=reason,
    )


def _commute_day(
    profile: AgentProfile, destinations: list[str], rng: random.Random,
) -> list[PlanStep]:
    workplace = _pick_destination(rng, destinations, exclude=profile.home_location)
    depart_am = rng.choice(_COMMUTE_DEPART_AM_PEAKS)
    depart_pm = rng.choice(_COMMUTE_RETURN_PM_PEAKS)
    errand_dest = _pick_destination(
        rng, destinations, exclude=workplace,
    )
    errand_hour = rng.choice(_ERRAND_HOURS[2:])  # afternoon errand
    leisure_dest = _pick_destination(
        rng, destinations, exclude=profile.home_location,
    )
    leisure_hour = rng.choice(_LEISURE_HOURS[3:])  # evening leisure

    return [
        _step(depart_am, "move", workplace, duration=480,
              activity="commute to workplace", reason="commute"),
        _step(f"{errand_hour}:00", "move", errand_dest, duration=30,
              activity="errand", reason="errand", social="open_to_chat"),
        _step(depart_pm, "move", profile.home_location, duration=20,
              activity="commute home", reason="commute"),
        _step(f"{leisure_hour}:00", "move", leisure_dest, duration=60,
              activity="leisure", reason="leisure", social="open_to_chat"),
        _step("21:30", "move", profile.home_location, duration=480,
              activity="rest at home", reason="end of day"),
    ]


def _remote_day(
    profile: AgentProfile, destinations: list[str], rng: random.Random,
) -> list[PlanStep]:
    morning_hour = rng.choice([8, 9])
    errand_hour = rng.choice(_ERRAND_HOURS)
    leisure_hour = rng.choice(_LEISURE_HOURS)
    errand_dest = _pick_destination(
        rng, destinations, exclude=profile.home_location,
    )
    leisure_dest = _pick_destination(
        rng, destinations, exclude=errand_dest,
    )
    return [
        _step(f"{morning_hour}:00", "stay", profile.home_location,
              duration=180, activity="remote work", reason="work"),
        _step(f"{errand_hour}:00", "move", errand_dest, duration=45,
              activity="errand", reason="errand", social="open_to_chat"),
        _step("13:00", "move", profile.home_location, duration=180,
              activity="afternoon work block", reason="work"),
        _step(f"{leisure_hour}:00", "move", leisure_dest, duration=60,
              activity="leisure outing", reason="leisure", social="open_to_chat"),
        _step("21:30", "move", profile.home_location, duration=480,
              activity="rest at home", reason="end of day"),
    ]


def _shift_day(
    profile: AgentProfile, destinations: list[str], rng: random.Random,
) -> list[PlanStep]:
    shift_start_hour = rng.choice([6, 14, 22])  # morning / afternoon / night
    workplace = _pick_destination(rng, destinations, exclude=profile.home_location)
    errand_dest = _pick_destination(rng, destinations, exclude=workplace)
    errand_hour = (shift_start_hour - 2) % 24
    return [
        _step(f"{errand_hour}:00", "move", errand_dest, duration=30,
              activity="pre-shift errand", reason="errand"),
        _step(f"{shift_start_hour}:00", "move", workplace, duration=480,
              activity="shift work", reason="work"),
        _step(f"{(shift_start_hour + 8) % 24}:30", "move", profile.home_location,
              duration=480, activity="post-shift rest", reason="end of shift"),
    ]


def _flexible_day(
    profile: AgentProfile, destinations: list[str], rng: random.Random,
) -> list[PlanStep]:
    """nonworking day: 2-3 errand/leisure outings spread through the day."""
    n_outings = rng.choice([2, 3])
    used: list[str] = []
    steps: list[PlanStep] = []
    hours_pool = sorted(rng.sample(_ERRAND_HOURS + _LEISURE_HOURS, k=n_outings + 1))
    for i, hour in enumerate(hours_pool[:-1]):
        dest = _pick_destination(
            rng, destinations,
            exclude=used[-1] if used else profile.home_location,
        )
        used.append(dest)
        kind = "errand" if i % 2 == 0 else "leisure"
        steps.append(_step(
            f"{hour}:00", "move", dest, duration=45,
            activity=kind, reason=kind,
            social="open_to_chat" if kind == "leisure" else "alone",
        ))
    steps.append(_step(
        f"{hours_pool[-1]}:00", "move", profile.home_location, duration=480,
        activity="return home", reason="end of day",
    ))
    return steps


_DISPATCH: dict[WorkMode, callable] = {  # type: ignore[type-arg]
    "commute": _commute_day,
    "remote": _remote_day,
    "shift": _shift_day,
    "nonworking": _flexible_day,
}


def build_scripted_plan(
    profile: AgentProfile,
    destinations: list[str],
    date: str,
    rng: random.Random,
) -> DailyPlan:
    """
    Build a day-shape DailyPlan branching on profile.work_mode.

    Falls back to `_flexible_day` when work_mode is missing (older profiles
    that haven't been re-sampled since the calibration change).
    """
    if not destinations:
        return DailyPlan(agent_id=profile.agent_id, date=date, steps=[])

    work_mode = profile.work_mode or "nonworking"
    builder = _DISPATCH.get(work_mode, _flexible_day)
    steps = builder(profile, destinations, rng)
    return DailyPlan(
        agent_id=profile.agent_id, date=date, steps=steps, current_step_index=0,
    )


__all__ = ["build_scripted_plan"]
