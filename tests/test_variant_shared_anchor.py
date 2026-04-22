"""Tests for SharedAnchorVariant (C — H_meaning)."""

from __future__ import annotations

from datetime import date, datetime
from random import Random

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention.service import AttentionService
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.policy_hack import (
    PhaseController,
    SharedAnchorVariant,
    VariantContext,
)


def _setup(n_agents: int, day_index: int, seed: int = 42) -> VariantContext:
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 22)
    attention = AttentionService(ledger=ledger, seed=seed)
    runtimes = tuple(
        AgentRuntime(
            profile=AgentProfile(
                agent_id=f"a{i:02d}", name=f"a{i:02d}", age=30,
                occupation="x", household="single", home_location="a",
            ),
            current_location="a",
        )
        for i in range(n_agents)
    )
    for r in runtimes:
        ledger.set_entity(EntityState(
            entity_id=r.profile.agent_id, location_id="a",
            position=Coord(x=0.0, y=0.0),
        ))
    pc = PhaseController(baseline_days=1, intervention_days=1, post_days=1)
    return VariantContext(
        day_index=day_index,
        simulated_date=date(2026, 4, 22),
        phase=pc.phase(day_index),
        ledger=ledger,
        attention_service=attention,
        runtimes=runtimes,
        rng=Random(seed),
        seed=seed,
    )


class TestSharedAnchor:
    def test_ratio_selects_n_agents(self):
        v = SharedAnchorVariant(share_ratio=0.10)
        ctx = _setup(n_agents=100, day_index=1)
        v.apply_intervention_start(ctx)
        # 10 agents picked
        assert len(v._anchor_ids) == 10

    def test_ceil_semantics_for_small_populations(self):
        v = SharedAnchorVariant(share_ratio=0.10)
        ctx = _setup(n_agents=5, day_index=1)
        v.apply_intervention_start(ctx)
        # ceil(5 × 0.10) = 1
        assert len(v._anchor_ids) == 1

    def test_same_feed_item_id_for_all_anchor_agents(self):
        v = SharedAnchorVariant(share_ratio=0.30)
        ctx = _setup(n_agents=10, day_index=1)
        v.apply_intervention_start(ctx)
        v.apply_day_start(ctx)
        delivered = ctx.attention_service._delivery_log  # type: ignore[attr-defined]
        delivered_records = [r for r in delivered if r.delivered]
        # All recipients receive the SAME feed_item_id
        feed_item_ids = {r.feed_item_id for r in delivered_records}
        assert len(feed_item_ids) == 1
        assert next(iter(feed_item_ids)) == f"shared_anchor_{ctx.seed}"

    def test_task_category(self):
        v = SharedAnchorVariant()
        ctx = _setup(n_agents=20, day_index=1)
        v.apply_intervention_start(ctx)
        v.apply_day_start(ctx)
        items = list(ctx.attention_service._feed_index.values())  # type: ignore[attr-defined]
        assert any(it.category == "task" for it in items)

    def test_task_chosen_from_templates(self):
        v = SharedAnchorVariant()
        ctx = _setup(n_agents=10, day_index=1)
        v.apply_intervention_start(ctx)
        assert v._chosen_task in v.task_templates

    def test_no_op_without_attention_service(self):
        """Skip gracefully if no attention service."""
        ledger = Ledger()
        ledger.current_time = datetime(2026, 4, 22)
        runtimes = tuple(
            AgentRuntime(
                profile=AgentProfile(
                    agent_id=f"a{i:02d}", name=f"a{i:02d}", age=30,
                    occupation="x", household="single", home_location="a",
                ),
                current_location="a",
            )
            for i in range(5)
        )
        for r in runtimes:
            ledger.set_entity(EntityState(
                entity_id=r.profile.agent_id, location_id="a",
                position=Coord(x=0.0, y=0.0),
            ))
        ctx = VariantContext(
            day_index=1, simulated_date=date(2026, 4, 22),
            phase="intervention", ledger=ledger,
            attention_service=None,  # no channel
            runtimes=runtimes, rng=Random(0), seed=0,
        )
        v = SharedAnchorVariant()
        v.apply_intervention_start(ctx)
        v.apply_day_start(ctx)  # should not raise
