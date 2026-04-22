"""Tests for PhoneFrictionVariant (B — H_pull)."""

from __future__ import annotations

from datetime import date, datetime
from random import Random

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention.models import DigitalProfile
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.policy_hack import (
    PhaseController,
    PhoneFrictionVariant,
    VariantContext,
)


def _runtime(agent_id: str, screen_hours: float = 4.0) -> AgentRuntime:
    profile = AgentProfile(
        agent_id=agent_id, name=agent_id, age=30, occupation="x",
        household="single", home_location="a",
        digital=DigitalProfile(
            daily_screen_hours=screen_hours,
            feed_bias="global",
            headphones_hours=2.0,
            notification_responsiveness=0.8,
        ),
    )
    return AgentRuntime(profile=profile, current_location="a")


def _ctx(runtimes, day_index: int, phase) -> VariantContext:
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 22)
    for r in runtimes:
        ledger.set_entity(EntityState(
            entity_id=r.profile.agent_id, location_id="a",
            position=Coord(x=0.0, y=0.0),
        ))
    return VariantContext(
        day_index=day_index,
        simulated_date=date(2026, 4, 22),
        phase=phase,
        ledger=ledger,
        attention_service=None,
        runtimes=tuple(runtimes),
        rng=Random(0),
        seed=0,
    )


class TestPhoneFriction:
    def test_intervention_start_halves_screen_hours(self):
        rt = _runtime("a1", screen_hours=4.0)
        v = PhoneFrictionVariant(friction_multiplier=0.5)
        ctx = _ctx([rt], day_index=4, phase="intervention")
        v.apply_intervention_start(ctx)
        assert rt.profile.digital.daily_screen_hours == 2.0

    def test_notification_responsiveness_scaled(self):
        rt = _runtime("a1", screen_hours=4.0)
        v = PhoneFrictionVariant(friction_multiplier=0.5)
        ctx = _ctx([rt], day_index=4, phase="intervention")
        v.apply_intervention_start(ctx)
        assert rt.profile.digital.notification_responsiveness == 0.4  # 0.8 × 0.5

    def test_feed_bias_switched_to_local(self):
        rt = _runtime("a1")
        v = PhoneFrictionVariant(friction_multiplier=0.5)
        ctx = _ctx([rt], day_index=4, phase="intervention")
        v.apply_intervention_start(ctx)
        assert rt.profile.digital.feed_bias == "local"

    def test_intervention_end_restores_original(self):
        rt = _runtime("a1", screen_hours=4.0)
        original_digital = rt.profile.digital
        v = PhoneFrictionVariant(friction_multiplier=0.5)

        # intervention start → modify
        ctx_in = _ctx([rt], day_index=4, phase="intervention")
        v.apply_intervention_start(ctx_in)
        assert rt.profile.digital.daily_screen_hours == 2.0

        # intervention end → restore
        ctx_post = _ctx([rt], day_index=10, phase="post")
        v.apply_intervention_end(ctx_post)
        assert rt.profile.digital == original_digital
        assert rt.profile.digital.daily_screen_hours == 4.0

    def test_apply_day_start_is_noop(self):
        """B variant's apply_day_start should not change anything."""
        rt = _runtime("a1", screen_hours=4.0)
        v = PhoneFrictionVariant(friction_multiplier=0.5)
        # First run intervention_start
        ctx = _ctx([rt], day_index=4, phase="intervention")
        v.apply_intervention_start(ctx)
        mid_hours = rt.profile.digital.daily_screen_hours
        # Call apply_day_start — should be no-op
        v.apply_day_start(ctx)
        assert rt.profile.digital.daily_screen_hours == mid_hours

    def test_multiple_agents_all_affected(self):
        runtimes = [_runtime(f"a{i}", screen_hours=3.0 + i) for i in range(3)]
        v = PhoneFrictionVariant(friction_multiplier=0.5)
        ctx = _ctx(runtimes, day_index=4, phase="intervention")
        v.apply_intervention_start(ctx)
        assert runtimes[0].profile.digital.daily_screen_hours == 1.5
        assert runtimes[1].profile.digital.daily_screen_hours == 2.0
        assert runtimes[2].profile.digital.daily_screen_hours == 2.5
