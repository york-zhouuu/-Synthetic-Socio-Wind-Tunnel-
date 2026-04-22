"""Tests for GlobalDistractionVariant (A' — paired mirror)."""

from __future__ import annotations

from datetime import date, datetime
from random import Random

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention.service import AttentionService
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.policy_hack import (
    GlobalDistractionVariant,
    HyperlocalPushVariant,
    VariantContext,
)


def _setup(n_agents: int, day_index: int, seed: int = 0) -> VariantContext:
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
    return VariantContext(
        day_index=day_index,
        simulated_date=date(2026, 4, 22),
        phase="intervention",
        ledger=ledger,
        attention_service=attention,
        runtimes=runtimes,
        rng=Random(seed),
        seed=seed,
    )


class TestGlobalDistraction:
    def test_is_mirror(self):
        v = GlobalDistractionVariant()
        assert v.is_mirror is True
        assert v.paired_variant == "hyperlocal_push"

    def test_default_daily_count_20(self):
        v = GlobalDistractionVariant()
        ctx = _setup(n_agents=4, day_index=1)
        v.apply_day_start(ctx)
        items = list(ctx.attention_service._feed_index.values())  # type: ignore[attr-defined]
        assert len(items) == 20

    def test_global_source_no_hyperlocal_radius(self):
        v = GlobalDistractionVariant()
        ctx = _setup(n_agents=4, day_index=1)
        v.apply_day_start(ctx)
        items = list(ctx.attention_service._feed_index.values())  # type: ignore[attr-defined]
        for it in items:
            assert it.source == "global_news"
            assert it.hyperlocal_radius is None
            assert it.category == "news_global"

    def test_targets_match_hyperlocal_first_half(self):
        """A' 与 A 同 seed 应选相同 target 集合（前一半 by agent_id 字典序）。"""
        a = HyperlocalPushVariant(target_location="cafe")
        ap = GlobalDistractionVariant()
        ctx_a = _setup(n_agents=10, day_index=1, seed=42)
        ctx_ap = _setup(n_agents=10, day_index=1, seed=42)

        a.apply_day_start(ctx_a)
        ap.apply_day_start(ctx_ap)

        # 比较"被推送到的 agent 集合"（不是 delivered 后剩下的）——
        # AttentionService 有 algorithmic bias filter 会对不同内容类型
        # 做不同 drop，所以只比较 recipient_id 全集（含 suppressed）
        recipients_a = {
            r.recipient_id for r in ctx_a.attention_service._delivery_log  # type: ignore[attr-defined]
        }
        recipients_ap = {
            r.recipient_id for r in ctx_ap.attention_service._delivery_log  # type: ignore[attr-defined]
        }
        assert recipients_a == recipients_ap

    def test_explicit_target_ids(self):
        v = GlobalDistractionVariant(target_agent_ids=("a02", "a03"))
        ctx = _setup(n_agents=5, day_index=1)
        v.apply_day_start(ctx)
        delivered = ctx.attention_service._delivery_log  # type: ignore[attr-defined]
        recipients = {r.recipient_id for r in delivered if r.delivered}
        assert recipients == {"a02", "a03"}
