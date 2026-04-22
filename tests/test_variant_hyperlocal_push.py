"""Tests for HyperlocalPushVariant (A — H_info)."""

from __future__ import annotations

from datetime import date, datetime
from random import Random

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention.service import AttentionService
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.policy_hack import (
    HyperlocalPushVariant,
    PhaseController,
    VariantContext,
)


def _setup_ctx(n_agents: int, day_index: int, seed: int = 0) -> VariantContext:
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 22, 0, 0, 0)
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
        simulated_date=date(2026, 4, 22) if day_index == 0 else date(2026, 4, 23),
        phase=pc.phase(day_index),
        ledger=ledger,
        attention_service=attention,
        runtimes=runtimes,
        rng=Random(seed),
        seed=seed,
    )


class TestHyperlocalPush:
    def test_default_picks_first_half_by_id(self):
        v = HyperlocalPushVariant(target_location="cafe_main")
        ctx = _setup_ctx(n_agents=6, day_index=1)
        v.apply_day_start(ctx)
        # 6 agents → 3 target（前一半 by id）
        delivered = ctx.attention_service._delivery_log  # type: ignore[attr-defined]
        # 1 feed_item → delivered to 3 agents
        recipients = {r.recipient_id for r in delivered if r.delivered}
        assert recipients == {"a00", "a01", "a02"}

    def test_multi_day_count(self):
        v = HyperlocalPushVariant(target_location="cafe_main")
        ctx_day1 = _setup_ctx(n_agents=4, day_index=1)
        v.apply_day_start(ctx_day1)
        count_after_1_call = len(ctx_day1.attention_service._delivery_log)  # type: ignore[attr-defined]
        # 4 agents → 2 target；1 feed_item × 2 delivered = 2 records
        assert count_after_1_call == 2

    def test_explicit_target_agent_ids(self):
        v = HyperlocalPushVariant(
            target_location="cafe_main",
            target_agent_ids=("a02", "a03"),
        )
        ctx = _setup_ctx(n_agents=5, day_index=1)
        v.apply_day_start(ctx)
        delivered = ctx.attention_service._delivery_log  # type: ignore[attr-defined]
        recipients = {r.recipient_id for r in delivered if r.delivered}
        assert recipients == {"a02", "a03"}

    def test_feed_item_has_hyperlocal_radius(self):
        v = HyperlocalPushVariant(
            target_location="cafe_main", hyperlocal_radius_m=800.0,
        )
        ctx = _setup_ctx(n_agents=2, day_index=1)
        v.apply_day_start(ctx)
        # Inspect injected feed items by recent feed_item_id
        feed_items = list(ctx.attention_service._feed_index.values())  # type: ignore[attr-defined]
        assert len(feed_items) == 1
        assert feed_items[0].hyperlocal_radius == 800.0
        assert feed_items[0].source == "local_news"
        assert feed_items[0].category == "event"

    def test_daily_push_count_multiple(self):
        v = HyperlocalPushVariant(
            target_location="cafe_main", daily_push_count=3,
        )
        ctx = _setup_ctx(n_agents=4, day_index=1)
        v.apply_day_start(ctx)
        feed_items = list(ctx.attention_service._feed_index.values())  # type: ignore[attr-defined]
        assert len(feed_items) == 3
