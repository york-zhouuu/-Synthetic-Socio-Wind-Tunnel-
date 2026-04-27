"""
Scripted plan generation for non-protagonist (Haiku-tier) agents.

Used when the simulation budget can't afford LLM calls per agent per day.
Day shape branches on `profile.work_mode` for weekdays + a separate weekend
shape that drops commute and emphasizes leisure/family time.

Public API: `build_scripted_plan(profile, destinations, date, rng) -> DailyPlan`
matches the legacy signature; existing callers continue to work.

Realism features (agent-realistic-routine, 2026-04-28):
- Per-agent `LifePattern` provides sticky preferred destinations + commute
  time offsets across all 14 sim days.
- `personality.routine_adherence` probabilistically gates LifePattern usage:
  high adherence → 80% of decisions use LifePattern; low → 20%.
- 8 profile dimensions condition day-shape:
  family_composition / unpaid_child_care_hours / vehicles_at_dwelling /
  community_tenure_5yr / english_proficiency / personality.routine_adherence
  / personality.openness / age (via family_composition link).
- Popular Times JSON, when present at data/calibration/lanecove_popular_times.json,
  weights destination sampling by hour-of-week heat (graceful fallback to
  uniform when absent).
"""

from __future__ import annotations

import json
import random
from datetime import date as _date
from datetime import datetime as _datetime
from pathlib import Path

from .planner import DailyPlan, PlanStep
from .profile import AgentProfile, LifePattern, WorkMode


# Hour-window anchors. Real bell shape comes from per-agent
# `LifePattern.morning_commute_minute` / `evening_return_minute` (sampled
# gaussian at population time); these constants set the hour bucket.
_COMMUTE_DEPART_HOUR = 8
_COMMUTE_RETURN_HOUR = 17
_ERRAND_HOURS = (10, 11, 14, 15, 16)
_LEISURE_HOURS = (10, 11, 17, 18, 19, 20)


# ---------------------------------------------------------------------------
# Popular Times graceful loader (cached at module level)
# ---------------------------------------------------------------------------

_POPULAR_TIMES_PATH = (
    Path(__file__).resolve().parents[2]
    / "data" / "calibration" / "lanecove_popular_times.json"
)
_POPULAR_TIMES_CACHE: dict | None = None
_POPULAR_TIMES_LOADED = False


def _load_popular_times() -> dict | None:
    """
    Lazy-load Popular Times JSON if present. Returns None on missing/invalid.
    Cached at module level so we only read disk once per process.
    """
    global _POPULAR_TIMES_CACHE, _POPULAR_TIMES_LOADED
    if _POPULAR_TIMES_LOADED:
        return _POPULAR_TIMES_CACHE
    _POPULAR_TIMES_LOADED = True
    if not _POPULAR_TIMES_PATH.exists():
        return None
    try:
        data = json.loads(_POPULAR_TIMES_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    # Normalize to dict[poi_id → 7×24 grid of intensity ints]
    out: dict[str, list[list[int]]] = {}
    for poi in data.get("pois", []):
        pid = poi.get("id") or poi.get("place_id") or poi.get("name")
        pop = poi.get("popularity")
        if pid and isinstance(pop, list) and len(pop) == 7:
            out[pid] = pop
    _POPULAR_TIMES_CACHE = out or None
    return _POPULAR_TIMES_CACHE


# ---------------------------------------------------------------------------
# LifePattern gating
# ---------------------------------------------------------------------------

def _use_lifepattern(rng: random.Random, routine_adherence: float) -> bool:
    """Probability gate: should we use LifePattern preferred_* this time?"""
    if routine_adherence > 0.7:
        threshold = 0.80
    elif routine_adherence >= 0.4:
        threshold = 0.50
    else:
        threshold = 0.20
    return rng.random() < threshold


# ---------------------------------------------------------------------------
# Destination picker (Popular Times-weighted with graceful fallback)
# ---------------------------------------------------------------------------

def _pick_destination(
    rng: random.Random,
    destinations: list[str],
    *,
    exclude: str | None = None,
    current_hour: int | None = None,
    weekday: int = 0,
) -> str:
    """
    Pick a destination. When Popular Times data + current_hour are both
    available, weight by hour-of-week heat. Otherwise uniform.

    weekday: 0=Mon..6=Sun, used to index into 7-day Popular Times grid.
    """
    pool = [d for d in destinations if d != exclude] if exclude else destinations
    if not pool:
        return destinations[0] if destinations else "home"

    if current_hour is None:
        return rng.choice(pool)

    pop_times = _load_popular_times()
    if pop_times is None:
        return rng.choice(pool)

    weights = []
    has_signal = False
    for poi in pool:
        grid = pop_times.get(poi)
        if grid and 0 <= weekday < len(grid) and 0 <= current_hour < len(grid[weekday]):
            w = max(1, int(grid[weekday][current_hour]))  # avoid zero
            has_signal = True
        else:
            w = 50  # neutral fallback weight
        weights.append(w)

    if not has_signal:
        return rng.choice(pool)
    return rng.choices(pool, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _step(time: str, action: str, destination: str | None, *,
          duration: int, activity: str, social: str = "alone",
          reason: str = "") -> PlanStep:
    return PlanStep(
        time=time, action=action, destination=destination,
        duration_minutes=duration, activity=activity,
        social_intent=social,  # type: ignore[arg-type]
        reason=reason,
    )


def _maybe_lifepattern_dest(
    profile: AgentProfile,
    rng: random.Random,
    field: str,
) -> str | None:
    """Return LifePattern.<field> when adherence-gated; else None (caller falls back)."""
    lp = profile.life_pattern
    if lp is None:
        return None
    routine = profile.personality.routine_adherence
    if not _use_lifepattern(rng, routine):
        return None
    return getattr(lp, field, None)


def _commute_minute(profile: AgentProfile, evening: bool = False) -> int:
    """Read LifePattern offset; default to minute 30 of the hour."""
    lp = profile.life_pattern
    if lp is None:
        return 30
    return lp.evening_return_minute if evening else lp.morning_commute_minute


def _wants_school_pickup(profile: AgentProfile) -> bool:
    return profile.family_composition == "couple_kids_under_15" \
        or profile.family_composition == "one_parent_family"


def _is_high_care(profile: AgentProfile) -> bool:
    return profile.unpaid_child_care_hours in ("15_29", "30plus") \
        or profile.unpaid_disability_care_hours == "yes"


def _has_no_car(profile: AgentProfile) -> bool:
    return profile.vehicles_at_dwelling == "0"


def _community_lock_strength(profile: AgentProfile) -> str:
    """Returns 'newcomer' / 'mid' / 'established' for routine adherence."""
    return profile.community_tenure_5yr or "mid"


def _maybe_transit_via(
    rng: random.Random, destinations: list[str], home: str | None, work: str,
) -> str | None:
    """
    For 0-car agents: pick a transit-like via-point (any other destination
    along the way). Lightweight — just rng-pick once.
    """
    pool = [d for d in destinations if d not in (home, work)]
    return rng.choice(pool) if pool else None


# ---------------------------------------------------------------------------
# Weekday day-shapes (4 work modes, with realism conditioning)
# ---------------------------------------------------------------------------

def _commute_day(
    profile: AgentProfile,
    destinations: list[str],
    rng: random.Random,
    *,
    weekday_idx: int,
) -> list[PlanStep]:
    workplace = _pick_destination(
        rng, destinations, exclude=profile.home_location,
        current_hour=_COMMUTE_DEPART_HOUR, weekday=weekday_idx,
    )
    depart_minute = _commute_minute(profile)
    return_minute = _commute_minute(profile, evening=True)
    depart_am = f"{_COMMUTE_DEPART_HOUR}:{depart_minute:02d}"
    depart_pm = f"{_COMMUTE_RETURN_HOUR}:{return_minute:02d}"

    # 0-car agent: insert transit via-point on commute
    via_step = None
    if _has_no_car(profile):
        via = _maybe_transit_via(rng, destinations, profile.home_location, workplace)
        if via:
            via_step = _step(
                f"{_COMMUTE_DEPART_HOUR}:{max(0, depart_minute - 10):02d}",
                "move", via, duration=10,
                activity="transit transfer", reason="commute",
            )

    # Errand: high-care agents constrain to 9-15 (school hours)
    if _is_high_care(profile):
        errand_hour = rng.choice([9, 10, 11, 13, 14])
    else:
        errand_hour = rng.choice(_ERRAND_HOURS[2:])  # afternoon
    errand_dest = (
        _maybe_lifepattern_dest(profile, rng, "preferred_errand_destination")
        or _pick_destination(
            rng, destinations, exclude=workplace,
            current_hour=errand_hour, weekday=weekday_idx,
        )
    )

    # Leisure: cafe-like, evening
    leisure_hour = rng.choice(_LEISURE_HOURS[3:])
    leisure_dest = (
        _maybe_lifepattern_dest(profile, rng, "preferred_cafe")
        or _pick_destination(
            rng, destinations, exclude=profile.home_location,
            current_hour=leisure_hour, weekday=weekday_idx,
        )
    )

    steps: list[PlanStep] = []
    if via_step:
        steps.append(via_step)
    steps.extend([
        _step(depart_am, "move", workplace, duration=480,
              activity="commute to workplace", reason="commute"),
    ])

    # School pickup for couple_kids_under_15 / one_parent_family
    if _wants_school_pickup(profile):
        # Pick a pseudo-school destination (any nearby; a future change
        # could tag school POIs in atlas explicitly)
        school_dest = _pick_destination(rng, destinations, exclude=workplace)
        steps.append(_step(
            "15:00", "move", school_dest, duration=30,
            activity="school pickup for kids", reason="kids", social="open_to_chat",
        ))
        # 18:30 family dinner anchor at home
        steps.append(_step(
            "18:30", "stay", profile.home_location, duration=60,
            activity="family dinner", reason="family",
        ))

    steps.extend([
        _step(f"{errand_hour}:00", "move", errand_dest, duration=30,
              activity="errand", reason="errand", social="open_to_chat"),
        _step(depart_pm, "move", profile.home_location, duration=20,
              activity="commute home", reason="commute"),
        _step(f"{leisure_hour}:00", "move", leisure_dest, duration=60,
              activity="leisure", reason="leisure", social="open_to_chat"),
        _step("21:30", "move", profile.home_location, duration=480,
              activity="rest at home", reason="end of day"),
    ])
    return steps


def _remote_day(
    profile: AgentProfile,
    destinations: list[str],
    rng: random.Random,
    *,
    weekday_idx: int,
) -> list[PlanStep]:
    morning_hour = rng.choice([8, 9])
    errand_hour = rng.choice(
        [9, 10, 11, 13, 14] if _is_high_care(profile) else _ERRAND_HOURS
    )
    leisure_hour = rng.choice(_LEISURE_HOURS)

    errand_dest = (
        _maybe_lifepattern_dest(profile, rng, "preferred_errand_destination")
        or _pick_destination(
            rng, destinations, exclude=profile.home_location,
            current_hour=errand_hour, weekday=weekday_idx,
        )
    )
    leisure_dest = (
        _maybe_lifepattern_dest(profile, rng, "preferred_leisure_park")
        or _pick_destination(
            rng, destinations, exclude=errand_dest,
            current_hour=leisure_hour, weekday=weekday_idx,
        )
    )

    steps = [
        _step(f"{morning_hour}:00", "stay", profile.home_location,
              duration=180, activity="remote work", reason="work"),
        _step(f"{errand_hour}:00", "move", errand_dest, duration=45,
              activity="errand", reason="errand", social="open_to_chat"),
        _step("13:00", "move", profile.home_location, duration=180,
              activity="afternoon work block", reason="work"),
    ]

    if _wants_school_pickup(profile):
        school_dest = _pick_destination(rng, destinations, exclude=profile.home_location)
        steps.append(_step(
            "15:00", "move", school_dest, duration=30,
            activity="school pickup for kids", reason="kids", social="open_to_chat",
        ))

    steps.extend([
        _step(f"{leisure_hour}:00", "move", leisure_dest, duration=60,
              activity="leisure outing", reason="leisure", social="open_to_chat"),
        _step("21:30", "move", profile.home_location, duration=480,
              activity="rest at home", reason="end of day"),
    ])
    return steps


def _shift_day(
    profile: AgentProfile,
    destinations: list[str],
    rng: random.Random,
    *,
    weekday_idx: int,
) -> list[PlanStep]:
    shift_start_hour = rng.choice([6, 14, 22])
    workplace = _pick_destination(
        rng, destinations, exclude=profile.home_location,
        current_hour=shift_start_hour, weekday=weekday_idx,
    )
    errand_dest = (
        _maybe_lifepattern_dest(profile, rng, "preferred_errand_destination")
        or _pick_destination(rng, destinations, exclude=workplace)
    )
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
    profile: AgentProfile,
    destinations: list[str],
    rng: random.Random,
    *,
    weekday_idx: int,
) -> list[PlanStep]:
    """nonworking weekday: 2-3 errand/leisure outings spread through the day."""
    n_outings = rng.choice([2, 3])

    # Newcomers explore (more outings, more diverse); openness amplifies
    if profile.community_tenure_5yr == "new_<1yr":
        n_outings = min(3, n_outings + 1)

    used: list[str] = []
    steps: list[PlanStep] = []
    hours_pool = sorted(rng.sample(_ERRAND_HOURS + _LEISURE_HOURS, k=n_outings + 1))
    for i, hour in enumerate(hours_pool[:-1]):
        kind = "errand" if i % 2 == 0 else "leisure"
        # LifePattern gating per-step
        if kind == "errand":
            dest = _maybe_lifepattern_dest(profile, rng, "preferred_errand_destination")
        else:
            dest = _maybe_lifepattern_dest(profile, rng, "preferred_leisure_park") \
                or _maybe_lifepattern_dest(profile, rng, "preferred_cafe")
        if not dest:
            dest = _pick_destination(
                rng, destinations,
                exclude=used[-1] if used else profile.home_location,
                current_hour=hour, weekday=weekday_idx,
            )
        used.append(dest)
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


_WEEKDAY_DISPATCH: dict[WorkMode, callable] = {  # type: ignore[type-arg]
    "commute": _commute_day,
    "remote": _remote_day,
    "shift": _shift_day,
    "nonworking": _flexible_day,
}


# ---------------------------------------------------------------------------
# Weekend day-shape (no commute; family + leisure dominant)
# ---------------------------------------------------------------------------

def _weekend_day_shape(
    profile: AgentProfile,
    destinations: list[str],
    rng: random.Random,
    *,
    weekday_idx: int,
) -> list[PlanStep]:
    """
    Weekend: morning_at_home longer; AM errand; PM leisure outing;
    evening family time at home. Anchors weekend_outing_destination.
    """
    # AM errand (groceries / pharmacy)
    am_hour = rng.choice([9, 10, 11])
    errand_dest = (
        _maybe_lifepattern_dest(profile, rng, "preferred_errand_destination")
        or _pick_destination(
            rng, destinations, exclude=profile.home_location,
            current_hour=am_hour, weekday=weekday_idx,
        )
    )

    # PM leisure outing — weekend_outing_destination if LifePattern locked
    pm_hour = rng.choice([13, 14, 15, 16])
    outing_dest = (
        _maybe_lifepattern_dest(profile, rng, "weekend_outing_destination")
        or _maybe_lifepattern_dest(profile, rng, "preferred_leisure_park")
        or _pick_destination(
            rng, destinations, exclude=errand_dest,
            current_hour=pm_hour, weekday=weekday_idx,
        )
    )

    # Evening cafe / social if open / extraverted
    extraversion = profile.personality.extraversion
    steps = [
        _step("8:30", "stay", profile.home_location, duration=120,
              activity="weekend morning at home", reason="weekend"),
        _step(f"{am_hour}:00", "move", errand_dest, duration=45,
              activity="weekend errand", reason="errand"),
        _step("12:00", "stay", profile.home_location, duration=60,
              activity="lunch at home", reason="meal"),
        _step(f"{pm_hour}:00", "move", outing_dest, duration=120,
              activity="weekend outing", reason="leisure",
              social="open_to_chat" if extraversion > 0.4 else "alone"),
    ]

    if extraversion > 0.6:
        evening_dest = (
            _maybe_lifepattern_dest(profile, rng, "preferred_cafe")
            or _pick_destination(
                rng, destinations, exclude=outing_dest,
                current_hour=19, weekday=weekday_idx,
            )
        )
        steps.append(_step(
            "19:00", "move", evening_dest, duration=90,
            activity="evening social", reason="leisure",
            social="seeking_company",
        ))

    steps.append(_step(
        "21:00", "move", profile.home_location, duration=540,
        activity="weekend rest", reason="end of day",
    ))
    return steps


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _parse_weekday_idx(date_input) -> int:
    """Extract Mon=0..Sun=6 from str or date object."""
    if isinstance(date_input, _date) and not isinstance(date_input, _datetime):
        return date_input.weekday()
    if isinstance(date_input, _datetime):
        return date_input.weekday()
    try:
        d = _date.fromisoformat(str(date_input))
        return d.weekday()
    except (ValueError, TypeError):
        return 0  # default Monday for unparseable dates


def build_scripted_plan(
    profile: AgentProfile,
    destinations: list[str],
    date: str,
    rng: random.Random,
) -> DailyPlan:
    """
    Build a day-shape DailyPlan branching on weekday/weekend × work_mode.

    Realism features (agent-realistic-routine):
    - Weekday + weekend differentiation
    - LifePattern preferred destinations gated by routine_adherence
    - 8 profile dimensions condition step generation
    - Popular Times weighted destination sampling (graceful fallback)
    """
    if not destinations:
        return DailyPlan(agent_id=profile.agent_id, date=date, steps=[])

    weekday_idx = _parse_weekday_idx(date)
    is_weekend = weekday_idx >= 5

    if is_weekend:
        steps = _weekend_day_shape(profile, destinations, rng, weekday_idx=weekday_idx)
    else:
        work_mode = profile.work_mode or "nonworking"
        builder = _WEEKDAY_DISPATCH.get(work_mode, _flexible_day)
        steps = builder(profile, destinations, rng, weekday_idx=weekday_idx)

    return DailyPlan(
        agent_id=profile.agent_id, date=date, steps=steps, current_step_index=0,
    )


__all__ = ["build_scripted_plan"]
