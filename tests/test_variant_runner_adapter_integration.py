"""E2E integration tests: VariantRunnerAdapter + MultiDayRunner."""

from __future__ import annotations

from datetime import date, datetime

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention.models import DigitalProfile
from synthetic_socio_wind_tunnel.attention.service import AttentionService
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import MultiDayRunner, Orchestrator
from synthetic_socio_wind_tunnel.policy_hack import (
    HyperlocalPushVariant,
    PhaseController,
    PhoneFrictionVariant,
    VariantRunnerAdapter,
)


def _atlas() -> Atlas:
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "A", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .add_outdoor("cafe_main", "Cafe", area_type="street")
        .polygon([(20, 0), (30, 0), (30, 10), (20, 10)])
        .end_outdoor()
        .connect("a", "cafe_main", path_type="road", distance=5.0)
        .build()
    )
    return Atlas(region)


def _agent(agent_id: str, screen_hours: float = 4.0) -> AgentRuntime:
    profile = AgentProfile(
        agent_id=agent_id, name=agent_id, age=30, occupation="x",
        household="single", home_location="a",
        digital=DigitalProfile(daily_screen_hours=screen_hours),
    )
    return AgentRuntime(profile=profile, current_location="a")


def _build_stack(agents, start_date, *, with_attention=True):
    atlas = _atlas()
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())
    for a in agents:
        ledger.set_entity(EntityState(
            entity_id=a.profile.agent_id, location_id="a",
            position=Coord(x=0.0, y=0.0),
        ))
    attention = AttentionService(ledger=ledger, seed=0) if with_attention else None
    orch = Orchestrator(
        atlas, ledger, agents, attention_service=attention,
    )
    return orch, attention


class TestHyperlocalPushE2E:
    def test_14_day_result_has_variant_metadata(self):
        agents = [_agent(f"a{i:02d}") for i in range(6)]
        orch, attention = _build_stack(agents, date(2026, 4, 22))

        runner = MultiDayRunner(orchestrator=orch, seed=42)
        variant = HyperlocalPushVariant(target_location="cafe_main")
        controller = PhaseController(baseline_days=1, intervention_days=1, post_days=1)
        adapter = VariantRunnerAdapter(variant, controller, seed=42)
        adapter.attach_to(runner)

        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=3,
            on_day_start=adapter.on_day_start,
        )
        adapter.augment_result_metadata(result)

        assert "variant_metadata" in result.metadata
        assert result.metadata["variant_metadata"]["name"] == "hyperlocal_push"
        assert result.metadata["variant_metadata"]["hypothesis"] == "H_info"
        assert "phase_config" in result.metadata
        assert result.metadata["phase_config"]["baseline_days"] == 1
        assert result.metadata["seed"] == 42

    def test_feeds_delivered_during_intervention_only(self):
        agents = [_agent(f"a{i:02d}") for i in range(4)]
        orch, attention = _build_stack(agents, date(2026, 4, 22))

        runner = MultiDayRunner(orchestrator=orch, seed=0)
        variant = HyperlocalPushVariant(target_location="cafe_main")
        controller = PhaseController(baseline_days=1, intervention_days=1, post_days=1)
        adapter = VariantRunnerAdapter(variant, controller, seed=0)
        adapter.attach_to(runner)

        runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=3,
            on_day_start=adapter.on_day_start,
        )

        # Only 1 intervention day → 1 feed_item pushed
        feed_items = list(attention._feed_index.values())  # type: ignore[attr-defined]
        hyperlocal_items = [
            it for it in feed_items if it.origin_hack_id == "hyperlocal_push"
        ]
        assert len(hyperlocal_items) == 1


class TestPhoneFrictionE2E:
    def test_profile_restored_after_intervention(self):
        agents = [_agent(f"a{i}", screen_hours=4.0) for i in range(3)]
        original_digitals = [a.profile.digital for a in agents]
        orch, _ = _build_stack(agents, date(2026, 4, 22))

        runner = MultiDayRunner(orchestrator=orch, seed=0)
        variant = PhoneFrictionVariant(friction_multiplier=0.5)
        controller = PhaseController(baseline_days=1, intervention_days=1, post_days=1)
        adapter = VariantRunnerAdapter(variant, controller, seed=0)
        adapter.attach_to(runner)

        runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=3,
            on_day_start=adapter.on_day_start,
        )

        # After post day, all profiles should be restored
        for agent, original in zip(agents, original_digitals):
            assert agent.profile.digital == original
            assert agent.profile.digital.daily_screen_hours == 4.0


class TestBaselineNoVariant:
    def test_no_variant_no_metadata_keys(self):
        """未挂 adapter 时 MultiDayResult.metadata 只有 mode。"""
        agents = [_agent(f"a{i}") for i in range(2)]
        orch, _ = _build_stack(agents, date(2026, 4, 22))

        runner = MultiDayRunner(orchestrator=orch, seed=0)
        result = runner.run_multi_day(
            start_date=date(2026, 4, 22), num_days=1,
        )
        assert "variant_metadata" not in result.metadata
        assert "phase_config" not in result.metadata
