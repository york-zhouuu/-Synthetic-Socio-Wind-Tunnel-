"""Tests for HyperlocalPushVariant with PushPersonalizer integration."""

from __future__ import annotations

import random
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.policy_hack import (
    HyperlocalPushVariant,
    VariantContext,
    PUSH_TEMPLATES,
)


def _runtime(agent_id: str, **profile_kw) -> AgentRuntime:
    base = dict(
        agent_id=agent_id, name=agent_id, age=30, occupation="x",
        household="single", home_location="home",
        personality=PersonalityTraits(),
    )
    base.update(profile_kw)
    return AgentRuntime(profile=AgentProfile(**base), current_location="home")


def _ctx(runtimes, seed: int = 42) -> VariantContext:
    attention = MagicMock()
    attention.inject_feed_item = MagicMock()
    return VariantContext(
        day_index=2, simulated_date=date(2026, 5, 8),
        phase="intervention",
        ledger=MagicMock(),
        attention_service=attention,
        runtimes=tuple(runtimes),
        rng=random.Random(seed),
        seed=seed,
    )


class TestPersonalizedPath:

    def test_each_target_gets_unique_feed_item(self):
        rts = [
            _runtime("a_mom", age=35, household="family_with_kids",
                     family_composition="couple_kids_under_15"),
            _runtime("b_emma", age=25, household="single"),
            _runtime("c_joe", age=70),
        ]
        v = HyperlocalPushVariant(
            target_location="cafe_main",
            target_agent_ids=("a_mom", "b_emma", "c_joe"),
            use_personalizer=True,
        )
        ctx = _ctx(rts)
        v.apply_day_start(ctx)

        # 3 separate inject_feed_item calls (one per recipient)
        assert ctx.attention_service.inject_feed_item.call_count == 3

        # Collect all injected FeedItems
        injected_items = []
        for call in ctx.attention_service.inject_feed_item.call_args_list:
            args, kwargs = call
            item = args[0] if args else kwargs.get("feed_item") or kwargs.get("item")
            recipients = args[1] if len(args) > 1 else kwargs.get("recipients", [])
            injected_items.append((item, recipients))

        contents = {item.content for item, _ in injected_items}
        assert len(contents) >= 2, (
            f"3 different audience tags should yield >= 2 unique contents; "
            f"got {len(contents)}"
        )

        # All share same topic_id
        topic_ids = {item.topic_id for item, _ in injected_items}
        assert len(topic_ids) == 1, "all personalized items same day same push must share topic_id"
        assert next(iter(topic_ids)) is not None

        # Each call delivers to single recipient
        for _, recipients in injected_items:
            assert len(list(recipients)) == 1

    def test_target_audience_tags_propagated(self):
        rts = [_runtime("emma")]
        v = HyperlocalPushVariant(
            target_location="X",
            target_agent_ids=("emma",),
            use_personalizer=True,
            # restrict to one template for predictability
            push_template_pool=(PUSH_TEMPLATES[0],),  # market
        )
        ctx = _ctx(rts)
        v.apply_day_start(ctx)
        item = ctx.attention_service.inject_feed_item.call_args_list[0][0][0]
        assert item.target_audience_tags == ("parents", "young_adult")


class TestLegacyPath:

    def test_use_personalizer_false_keeps_old_behavior(self):
        rts = [_runtime(f"a_{i}") for i in range(3)]
        v = HyperlocalPushVariant(
            target_location="X",
            target_agent_ids=tuple(r.profile.agent_id for r in rts),
            use_personalizer=False,
        )
        ctx = _ctx(rts)
        v.apply_day_start(ctx)
        # Single inject (broadcast)
        assert ctx.attention_service.inject_feed_item.call_count == 1
        item, recipients = ctx.attention_service.inject_feed_item.call_args_list[0][0]
        # No topic_id when legacy
        assert item.topic_id is None
        # Broadcast to all 3
        assert len(list(recipients)) == 3


class TestVariantConstruction:

    def test_default_use_personalizer_true(self):
        v = HyperlocalPushVariant(target_location="X")
        assert v.use_personalizer is True
        assert len(v.push_template_pool) >= 5
