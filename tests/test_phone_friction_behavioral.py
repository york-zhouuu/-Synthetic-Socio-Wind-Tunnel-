"""Tests for PhoneFrictionVariant's behavioral injection (B3 fix).

Original variant only mutated `profile.digital`, which has no movement reader
in this pipeline → variant was operationally inert. The fix injects a
`friction_nudge` FeedItem each intervention day so attention → memory →
replan produces real plan-level differences vs baseline.
"""

from __future__ import annotations

from datetime import date
from random import Random
from unittest.mock import MagicMock

from synthetic_socio_wind_tunnel.policy_hack.base import VariantContext
from synthetic_socio_wind_tunnel.policy_hack.variants.phone_friction import (
    PhoneFrictionVariant,
)


def _make_runtime(agent_id: str) -> MagicMock:
    rt = MagicMock()
    rt.profile.agent_id = agent_id
    return rt


def _ctx(runtimes, attention) -> VariantContext:
    return VariantContext(
        day_index=0,
        simulated_date=date(2026, 5, 8),
        phase="intervention",
        ledger=MagicMock(),
        attention_service=attention,
        runtimes=runtimes,
        rng=Random(42),
        seed=42,
    )


class TestApplyDayStartInjectsFeedItem:

    def test_inject_called_once_per_day(self):
        attention = MagicMock()
        runtimes = tuple(_make_runtime(f"a{i}") for i in range(20))
        v = PhoneFrictionVariant()

        v.apply_day_start(_ctx(runtimes, attention))

        assert attention.inject_feed_item.call_count == 1, \
            "intervention day SHALL inject exactly one nudge per call"

    def test_inject_args_match_friction_nudge(self):
        attention = MagicMock()
        runtimes = tuple(_make_runtime(f"a{i}") for i in range(20))
        v = PhoneFrictionVariant()

        v.apply_day_start(_ctx(runtimes, attention))

        item, recipients = attention.inject_feed_item.call_args[0]
        assert item.origin_hack_id == "phone_friction"
        assert item.category == "self_reflection"
        assert item.source == "neighbourhood"  # see variant docstring
        assert item.content in v.nudge_content_templates

    def test_no_op_without_attention_service(self):
        runtimes = tuple(_make_runtime(f"a{i}") for i in range(5))
        v = PhoneFrictionVariant()
        # No attention_service injected.
        ctx = VariantContext(
            day_index=0,
            simulated_date=date(2026, 5, 8),
            phase="intervention",
            ledger=MagicMock(),
            attention_service=None,
            runtimes=runtimes,
            rng=Random(42),
            seed=42,
        )
        # SHALL NOT raise.
        v.apply_day_start(ctx)


class TestNudgeTargetRatio:

    def test_full_ratio_targets_all(self):
        attention = MagicMock()
        runtimes = tuple(_make_runtime(f"a{i:02d}") for i in range(20))
        v = PhoneFrictionVariant(nudge_target_ratio=1.0)

        v.apply_day_start(_ctx(runtimes, attention))

        _item, recipients = attention.inject_feed_item.call_args[0]
        assert len(recipients) == 20

    def test_partial_ratio_targets_subset(self):
        attention = MagicMock()
        runtimes = tuple(_make_runtime(f"a{i:02d}") for i in range(20))
        v = PhoneFrictionVariant(nudge_target_ratio=0.3)

        v.apply_day_start(_ctx(runtimes, attention))

        _item, recipients = attention.inject_feed_item.call_args[0]
        # 0.3 * 20 = 6 (floor); SHALL be deterministic by lex order.
        assert len(recipients) == 6
        assert tuple(recipients) == tuple(f"a{i:02d}" for i in range(6))


class TestMetadataExposesPrimaryMetric:

    def test_primary_metric_is_encounter_per_day_median(self):
        v = PhoneFrictionVariant()
        meta = v.metadata_dict()
        assert meta["primary_metric_name"] == "encounter.per_day_median"
        # Sanity: SHALL not still be the degenerate phone_feed_proxy.
        assert meta["primary_metric_name"] != "attention.phone_feed_proxy"
