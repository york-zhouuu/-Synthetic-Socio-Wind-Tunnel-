"""Tests for agent.intent Intent hierarchy + AgentRuntime.step."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    AgentRuntime,
    DailyPlan,
    PlanStep,
)
from synthetic_socio_wind_tunnel.agent.intent import (
    ExamineIntent,
    Intent,
    LockIntent,
    MoveIntent,
    OpenDoorIntent,
    PickupIntent,
    UnlockIntent,
    WaitIntent,
)


# Minimal stand-in for TickContext so test_agent_intent.py doesn't depend on
# orchestrator module being importable yet.
@dataclass(frozen=True)
class _FakeTickContext:
    tick_index: int
    simulated_time: datetime
    observer_context: object = None


def _profile(agent_id: str = "emma", home: str = "home_a") -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id, name="Emma", age=30, occupation="writer",
        household="single", home_location=home,
    )


def _plan(*steps: PlanStep, agent_id: str = "emma") -> DailyPlan:
    return DailyPlan(agent_id=agent_id, date="2026-04-20", steps=list(steps))


class TestIntentBase:

    def test_base_exclusive_not_implemented(self):
        base = Intent()
        with pytest.raises(NotImplementedError):
            _ = base.exclusive

    def test_base_target_id_default_none(self):
        base = Intent()
        # target_id has default; accessing it doesn't raise on base
        assert base.target_id is None


class TestNonExclusive:

    def test_move_intent(self):
        intent = MoveIntent(to_location="cafe_a")
        assert intent.exclusive is False
        assert intent.target_id is None
        assert intent.to_location == "cafe_a"

    def test_wait_intent(self):
        intent = WaitIntent(reason="at_destination")
        assert intent.exclusive is False
        assert intent.target_id is None
        assert intent.reason == "at_destination"

    def test_wait_intent_default_reason(self):
        intent = WaitIntent()
        assert intent.reason == ""

    def test_examine_intent(self):
        intent = ExamineIntent(target="drawer_1")
        assert intent.exclusive is False
        assert intent.target_id is None  # examine 非独占，不 gate on target


class TestExclusive:

    def test_pickup_intent(self):
        intent = PickupIntent(item_id="umbrella_01")
        assert intent.exclusive is True
        assert intent.target_id == "umbrella_01"

    def test_open_door_intent(self):
        intent = OpenDoorIntent(door_id="door_main")
        assert intent.exclusive is True
        assert intent.target_id == "door_main"

    def test_unlock_intent(self):
        intent = UnlockIntent(door_id="door_safe", key_id="key_001")
        assert intent.exclusive is True
        assert intent.target_id == "door_safe"
        assert intent.key_id == "key_001"

    def test_unlock_intent_no_key(self):
        intent = UnlockIntent(door_id="door_safe")
        assert intent.key_id is None

    def test_lock_intent(self):
        intent = LockIntent(door_id="door_front", key_id="key_front")
        assert intent.exclusive is True
        assert intent.target_id == "door_front"


class TestFrozenHashable:

    def test_intent_is_frozen(self):
        intent = MoveIntent(to_location="cafe_a")
        with pytest.raises((AttributeError, Exception)):
            intent.to_location = "elsewhere"  # type: ignore

    def test_same_fields_equal_hash(self):
        a = MoveIntent(to_location="cafe_a")
        b = MoveIntent(to_location="cafe_a")
        assert a == b
        assert hash(a) == hash(b)

    def test_different_types_not_equal(self):
        assert MoveIntent(to_location="x") != WaitIntent()

    def test_usable_as_dict_key(self):
        d = {
            MoveIntent(to_location="cafe_a"): "emma",
            PickupIntent(item_id="key_01"): "bob",
        }
        assert d[MoveIntent(to_location="cafe_a")] == "emma"


# ==================== AgentRuntime.step ====================


class TestStepMapping:

    def test_no_plan_returns_wait(self):
        runtime = AgentRuntime(profile=_profile(), current_location="home_a")
        ctx = _FakeTickContext(tick_index=0, simulated_time=datetime(2026, 4, 20, 7, 0))
        intent = runtime.step(ctx)
        assert isinstance(intent, WaitIntent)
        assert intent.reason == "no_plan"

    def test_move_plan_step_maps_to_move_intent(self):
        plan = _plan(
            PlanStep(time="7:00", action="move", destination="cafe_a",
                     duration_minutes=30),
        )
        runtime = AgentRuntime(profile=_profile(), plan=plan, current_location="home_a")
        ctx = _FakeTickContext(tick_index=0, simulated_time=datetime(2026, 4, 20, 7, 0))
        intent = runtime.step(ctx)
        assert isinstance(intent, MoveIntent)
        assert intent.to_location == "cafe_a"

    def test_at_destination_returns_wait(self):
        plan = _plan(
            PlanStep(time="7:00", action="move", destination="cafe_a",
                     duration_minutes=30),
        )
        # Already at cafe_a
        runtime = AgentRuntime(profile=_profile(), plan=plan, current_location="cafe_a")
        ctx = _FakeTickContext(tick_index=0, simulated_time=datetime(2026, 4, 20, 7, 5))
        intent = runtime.step(ctx)
        assert isinstance(intent, WaitIntent)
        assert intent.reason == "at_destination"

    def test_stay_action_returns_wait(self):
        plan = _plan(
            PlanStep(time="8:00", action="stay", activity="having_coffee",
                     duration_minutes=30),
        )
        runtime = AgentRuntime(profile=_profile(), plan=plan, current_location="cafe_a")
        ctx = _FakeTickContext(tick_index=0, simulated_time=datetime(2026, 4, 20, 8, 0))
        intent = runtime.step(ctx)
        assert isinstance(intent, WaitIntent)
        assert intent.reason == "having_coffee"


class TestStepAutoAdvance:

    def test_expired_step_auto_advances(self):
        plan = _plan(
            PlanStep(time="7:00", action="move", destination="cafe_a",
                     duration_minutes=30),  # expires at 7:30
            PlanStep(time="7:30", action="move", destination="library",
                     duration_minutes=60),
        )
        runtime = AgentRuntime(profile=_profile(), plan=plan, current_location="cafe_a")
        # At 7:35 — first step window has expired
        ctx = _FakeTickContext(tick_index=0, simulated_time=datetime(2026, 4, 20, 7, 35))
        intent = runtime.step(ctx)
        assert isinstance(intent, MoveIntent)
        assert intent.to_location == "library"

    def test_multiple_expired_steps_advance_in_one_call(self):
        plan = _plan(
            PlanStep(time="7:00", action="move", destination="a", duration_minutes=30),
            PlanStep(time="7:30", action="move", destination="b", duration_minutes=30),
            PlanStep(time="8:00", action="move", destination="c", duration_minutes=30),
        )
        runtime = AgentRuntime(profile=_profile(), plan=plan, current_location="home")
        # at 8:15 — first two expired; should be on step #3 (destination=c)
        ctx = _FakeTickContext(tick_index=0, simulated_time=datetime(2026, 4, 20, 8, 15))
        intent = runtime.step(ctx)
        assert isinstance(intent, MoveIntent)
        assert intent.to_location == "c"

    def test_plan_exhausted_returns_wait(self):
        plan = _plan(
            PlanStep(time="7:00", action="move", destination="a", duration_minutes=30),
        )
        runtime = AgentRuntime(profile=_profile(), plan=plan, current_location="home")
        ctx = _FakeTickContext(tick_index=0, simulated_time=datetime(2026, 4, 20, 9, 0))
        intent = runtime.step(ctx)
        assert isinstance(intent, WaitIntent)
        assert intent.reason == "plan_exhausted"


class TestStepNoExclusiveIntents:

    def test_interact_does_not_produce_examine(self):
        plan = _plan(
            PlanStep(time="10:00", action="interact", activity="reading",
                     duration_minutes=60),
        )
        runtime = AgentRuntime(profile=_profile(), plan=plan, current_location="library")
        ctx = _FakeTickContext(tick_index=0, simulated_time=datetime(2026, 4, 20, 10, 0))
        intent = runtime.step(ctx)
        # This change's step() must not produce any exclusive Intent type
        assert not isinstance(intent, (ExamineIntent, PickupIntent, OpenDoorIntent,
                                        UnlockIntent, LockIntent))
        assert isinstance(intent, WaitIntent)


class TestStepPurity:

    def test_step_does_not_write_ledger(self):
        """step() is pure wrt Ledger — no Ledger instance is even accessible."""
        plan = _plan(
            PlanStep(time="7:00", action="move", destination="cafe_a",
                     duration_minutes=30),
        )
        runtime = AgentRuntime(profile=_profile(), plan=plan, current_location="home")
        ctx = _FakeTickContext(tick_index=0, simulated_time=datetime(2026, 4, 20, 7, 0))
        # Calling twice without advance_plan side-effects should be equivalent
        # when time doesn't cross a step boundary
        intent_1 = runtime.step(ctx)
        intent_2 = runtime.step(ctx)
        assert intent_1 == intent_2
