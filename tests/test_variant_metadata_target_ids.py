"""Tests that hp/gd variants expose resolved target_agent_ids via metadata_dict.

Required by the B1 fix: metric factory reads `target_agent_ids` from
variant_metadata to compute protag-only trajectory_deviation_m without
diluting the signal with 90 scripted agents.
"""

from __future__ import annotations

from datetime import date
from random import Random
from unittest.mock import MagicMock

from synthetic_socio_wind_tunnel.policy_hack.base import VariantContext
from synthetic_socio_wind_tunnel.policy_hack.variants.global_distraction import (
    GlobalDistractionVariant,
)
from synthetic_socio_wind_tunnel.policy_hack.variants.hyperlocal_push import (
    HyperlocalPushVariant,
)


def _make_runtime(agent_id: str) -> MagicMock:
    rt = MagicMock()
    rt.profile.agent_id = agent_id
    return rt


def _ctx(runtimes: tuple[MagicMock, ...]) -> VariantContext:
    return VariantContext(
        day_index=0,
        simulated_date=date(2026, 5, 8),
        phase="intervention",
        ledger=MagicMock(),
        attention_service=MagicMock(),
        runtimes=runtimes,
        rng=Random(42),
        seed=42,
    )


class TestHyperlocalPushExposesTargetIds:

    def test_metadata_before_apply_lacks_resolved_ids(self):
        v = HyperlocalPushVariant(target_location="park_a")
        meta = v.metadata_dict()
        # Pre-apply, no resolved cache yet.
        assert "target_agent_ids" not in meta or meta["target_agent_ids"] is None
        # target_location SHALL still be exposed.
        assert meta["target_location"] == "park_a"

    def test_metadata_after_apply_has_resolved_ids(self):
        runtimes = tuple(_make_runtime(f"a{i}") for i in range(10))
        v = HyperlocalPushVariant(target_location="park_a", use_personalizer=False)
        v.apply_day_start(_ctx(runtimes))

        meta = v.metadata_dict()
        assert "target_agent_ids" in meta
        # Default = first half (5 agents) by lexical sort.
        assert len(meta["target_agent_ids"]) == 5
        assert meta["target_agent_ids"] == tuple(sorted(f"a{i}" for i in range(10))[:5])

    def test_explicit_target_ids_preserved(self):
        runtimes = tuple(_make_runtime(f"a{i}") for i in range(10))
        explicit = ("a3", "a7")
        v = HyperlocalPushVariant(
            target_location="park_a",
            target_agent_ids=explicit,
            use_personalizer=False,
        )
        v.apply_day_start(_ctx(runtimes))
        meta = v.metadata_dict()
        assert meta["target_agent_ids"] == explicit


class TestGlobalDistractionExposesTargetIds:

    def test_metadata_after_apply_has_resolved_ids(self):
        runtimes = tuple(_make_runtime(f"a{i}") for i in range(20))
        v = GlobalDistractionVariant()
        v.apply_day_start(_ctx(runtimes))

        meta = v.metadata_dict()
        assert "target_agent_ids" in meta
        # Default = first half (10 of 20) by lexical sort.
        assert len(meta["target_agent_ids"]) == 10

    def test_metadata_before_apply_lacks_resolved_ids(self):
        v = GlobalDistractionVariant()
        meta = v.metadata_dict()
        assert "target_agent_ids" not in meta or meta["target_agent_ids"] is None
