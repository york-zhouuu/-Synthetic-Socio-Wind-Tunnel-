"""Tests for DigitalAttentionFilter and pipeline integration."""

from __future__ import annotations

import random
from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention import (
    AttentionService,
    AttentionState,
    DigitalProfile,
    FeedItem,
)
from synthetic_socio_wind_tunnel.perception.filters.digital_attention import (
    DigitalAttentionFilter,
)
from synthetic_socio_wind_tunnel.perception.models import (
    Observation,
    ObserverContext,
    SenseType,
)


def _obs(sense: SenseType, source_id: str, *, is_notable: bool = False,
         confidence: float = 1.0, tags: list[str] | None = None) -> Observation:
    return Observation(
        sense=sense,
        source_id=source_id,
        source_type="test",
        is_notable=is_notable,
        confidence=confidence,
        tags=tags or [],
    )


def _context(digital_state: AttentionState | None = None) -> ObserverContext:
    return ObserverContext(
        entity_id="emma",
        position=Coord(x=0.0, y=0.0),
        digital_state=digital_state,
    )


class TestConstruction:

    def test_invalid_leakage_rejected(self):
        with pytest.raises(ValueError):
            DigitalAttentionFilter(attention_leakage=1.5)
        with pytest.raises(ValueError):
            DigitalAttentionFilter(attention_leakage=-0.1)


class TestPassthrough:

    def test_none_digital_state_passes_through(self):
        filt = DigitalAttentionFilter()
        obs = _obs(SenseType.VISUAL, "v1", is_notable=True)
        ctx = _context(None)
        result = filt.apply(obs, ctx)
        assert result is obs


class TestAttentionLeakage:

    def test_physical_world_target_does_not_dampen(self):
        filt = DigitalAttentionFilter(
            attention_leakage=0.0,
            rng=random.Random(0),
        )
        obs = _obs(SenseType.VISUAL, "v1", is_notable=True)
        ctx = _context(AttentionState(attention_target="physical_world"))
        result = filt.apply(obs, ctx)
        assert result.is_notable is True

    def test_phone_feed_target_with_zero_leakage_always_drops_notable(self):
        """leakage=0.0 → physical notables always downgraded."""
        filt = DigitalAttentionFilter(
            attention_leakage=0.0,
            rng=random.Random(0),
        )
        obs = _obs(SenseType.VISUAL, "v1", is_notable=True)
        ctx = _context(AttentionState(attention_target="phone_feed"))
        result = filt.apply(obs, ctx)
        assert result.is_notable is False

    def test_phone_feed_target_with_full_leakage_keeps_notable(self):
        """leakage=1.0 → physical notables never downgraded."""
        filt = DigitalAttentionFilter(
            attention_leakage=1.0,
            rng=random.Random(0),
        )
        obs = _obs(SenseType.VISUAL, "v1", is_notable=True)
        ctx = _context(AttentionState(attention_target="phone_feed"))
        result = filt.apply(obs, ctx)
        assert result.is_notable is True

    def test_statistical_expectation(self):
        """Over 1000 trials with leakage=0.3 we expect ~300 notable retained."""
        filt = DigitalAttentionFilter(
            attention_leakage=0.3,
            rng=random.Random(42),
        )
        ctx = _context(AttentionState(attention_target="phone_feed"))
        kept = 0
        for i in range(1000):
            obs = _obs(SenseType.VISUAL, f"v_{i}", is_notable=True)
            result = filt.apply(obs, ctx)
            if result.is_notable:
                kept += 1
        # Expected ~300, allow ±80 for safety
        assert 220 <= kept <= 380, f"kept={kept}"

    def test_non_notable_unaffected(self):
        filt = DigitalAttentionFilter(
            attention_leakage=0.0,
            rng=random.Random(0),
        )
        obs = _obs(SenseType.VISUAL, "v1", is_notable=False)
        ctx = _context(AttentionState(attention_target="phone_feed"))
        result = filt.apply(obs, ctx)
        assert result is obs


class TestDigitalObservationTagging:

    def test_high_confidence_digital_not_marked_missed(self):
        filt = DigitalAttentionFilter(rng=random.Random(0))
        obs = _obs(SenseType.DIGITAL, "f_001", confidence=0.8)
        ctx = _context(AttentionState(attention_target="physical_world"))
        result = filt.apply(obs, ctx)
        assert "missed" not in result.tags

    def test_low_confidence_digital_marked_missed_when_not_attending(self):
        filt = DigitalAttentionFilter(rng=random.Random(0))
        obs = _obs(SenseType.DIGITAL, "f_001", confidence=0.3)
        ctx = _context(AttentionState(attention_target="physical_world"))
        result = filt.apply(obs, ctx)
        assert "missed" in result.tags

    def test_digital_when_attending_feed_no_missed(self):
        filt = DigitalAttentionFilter(rng=random.Random(0))
        obs = _obs(SenseType.DIGITAL, "f_001", confidence=0.3)
        ctx = _context(AttentionState(attention_target="phone_feed"))
        result = filt.apply(obs, ctx)
        assert "missed" not in result.tags


class TestPipelineIntegration:
    """Smoke test the integration with PerceptionPipeline."""

    def test_pipeline_default_excludes_filter(self):
        """By default, include_digital_filter=False → no DigitalAttentionFilter."""
        from synthetic_socio_wind_tunnel.atlas import Atlas
        from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
        from synthetic_socio_wind_tunnel.ledger import Ledger
        from synthetic_socio_wind_tunnel.perception import PerceptionPipeline

        region = (
            RegionBuilder("r1", "r1")
            .add_outdoor("street_a", "Street A", area_type="street")
            .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
            .end_outdoor()
            .build()
        )
        atlas = Atlas(region)
        ledger = Ledger()
        pipeline = PerceptionPipeline(atlas, ledger)
        # Internal check: no DigitalAttentionFilter in filter list
        assert all(
            type(f).__name__ != "DigitalAttentionFilter"
            for f in pipeline._filters
        )

    def test_pipeline_opt_in_adds_filter(self):
        from synthetic_socio_wind_tunnel.atlas import Atlas
        from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
        from synthetic_socio_wind_tunnel.ledger import Ledger
        from synthetic_socio_wind_tunnel.perception import PerceptionPipeline

        region = (
            RegionBuilder("r1", "r1")
            .add_outdoor("street_a", "Street A", area_type="street")
            .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
            .end_outdoor()
            .build()
        )
        atlas = Atlas(region)
        ledger = Ledger()
        service = AttentionService(ledger, seed=0)
        pipeline = PerceptionPipeline(
            atlas,
            ledger,
            include_digital_filter=True,
            attention_service=service,
        )
        assert any(
            type(f).__name__ == "DigitalAttentionFilter"
            for f in pipeline._filters
        )

    def test_digital_filter_requires_attention_service(self):
        from synthetic_socio_wind_tunnel.atlas import Atlas
        from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
        from synthetic_socio_wind_tunnel.ledger import Ledger
        from synthetic_socio_wind_tunnel.perception import PerceptionPipeline

        region = (
            RegionBuilder("r1", "r1")
            .add_outdoor("street_a", "Street A", area_type="street")
            .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
            .end_outdoor()
            .build()
        )
        atlas = Atlas(region)
        ledger = Ledger()
        with pytest.raises(ValueError):
            PerceptionPipeline(atlas, ledger, include_digital_filter=True)

    def _minimal_pipeline(self):
        from synthetic_socio_wind_tunnel.atlas import Atlas
        from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
        from synthetic_socio_wind_tunnel.ledger import Ledger
        from synthetic_socio_wind_tunnel.ledger.models import EntityState
        from synthetic_socio_wind_tunnel.perception import PerceptionPipeline

        region = (
            RegionBuilder("r1", "r1")
            .add_outdoor("street_a", "Street A", area_type="street")
            .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
            .end_outdoor()
            .build()
        )
        atlas = Atlas(region)
        ledger = Ledger()
        ledger.current_time = datetime(2026, 4, 20, 18, 0, 0)
        ledger.set_entity(EntityState(
            entity_id="emma",
            location_id="street_a",
            position=Coord(x=1.0, y=1.0),
        ))
        service = AttentionService(ledger, seed=0)
        pipeline = PerceptionPipeline(
            atlas,
            ledger,
            include_digital_filter=True,
            attention_service=service,
        )
        return pipeline, service, ledger

    def test_pipeline_injects_digital_observations(self):
        """With filter enabled + attention service, pending feed items show up."""
        pipeline, service, ledger = self._minimal_pipeline()
        item = FeedItem(
            feed_item_id="f_001",
            content="Sunset tasting!",
            source="local_news",
            created_at=ledger.current_time,
        )
        service.inject_feed_item(item, ["emma"])

        ctx = ObserverContext(
            entity_id="emma",
            position=Coord(x=1.0, y=1.0),
            location_id="street_a",
            digital_state=AttentionState(
                attention_target="phone_feed",
                pending_notifications=("f_001",),
                notification_responsiveness=0.8,
            ),
        )
        view = pipeline.render(ctx)
        digital = view.get_observations_by_sense(SenseType.DIGITAL)
        assert len(digital) == 1
        assert digital[0].source_id == "f_001"
        # confidence should come from digital_state.notification_responsiveness
        assert digital[0].confidence == 0.8


class TestConsumption:
    """Fix 2: pending feed items are consumed after render, not re-injected."""

    def _minimal_setup(self):
        from synthetic_socio_wind_tunnel.atlas import Atlas
        from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
        from synthetic_socio_wind_tunnel.ledger import Ledger
        from synthetic_socio_wind_tunnel.ledger.models import EntityState
        from synthetic_socio_wind_tunnel.perception import PerceptionPipeline

        region = (
            RegionBuilder("r1", "r1")
            .add_outdoor("street_a", "Street A", area_type="street")
            .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
            .end_outdoor()
            .build()
        )
        atlas = Atlas(region)
        ledger = Ledger()
        ledger.current_time = datetime(2026, 4, 20, 18, 0, 0)
        ledger.set_entity(EntityState(
            entity_id="emma",
            location_id="street_a",
            position=Coord(x=1.0, y=1.0),
        ))
        service = AttentionService(ledger, seed=0)
        pipeline = PerceptionPipeline(
            atlas,
            ledger,
            include_digital_filter=True,
            attention_service=service,
        )
        return pipeline, service, ledger

    def _render_ctx(self, service: AttentionService, agent_id: str = "emma") -> ObserverContext:
        return ObserverContext(
            entity_id=agent_id,
            position=Coord(x=1.0, y=1.0),
            location_id="street_a",
            digital_state=AttentionState(
                attention_target="phone_feed",
                pending_notifications=service.pending_for(agent_id),
                notification_responsiveness=0.7,
            ),
        )

    def test_feed_item_not_reinjected_on_second_render(self):
        pipeline, service, ledger = self._minimal_setup()
        item = FeedItem(
            feed_item_id="f_001",
            content="x",
            source="local_news",
            created_at=ledger.current_time,
        )
        service.inject_feed_item(item, ["emma"])

        view_1 = pipeline.render(self._render_ctx(service))
        view_2 = pipeline.render(self._render_ctx(service))

        assert len(view_1.get_observations_by_sense(SenseType.DIGITAL)) == 1
        assert len(view_2.get_observations_by_sense(SenseType.DIGITAL)) == 0

    def test_new_feed_item_between_renders_appears(self):
        pipeline, service, ledger = self._minimal_setup()
        item_a = FeedItem(
            feed_item_id="f_001",
            content="x",
            source="local_news",
            created_at=ledger.current_time,
        )
        service.inject_feed_item(item_a, ["emma"])
        pipeline.render(self._render_ctx(service))  # consumes f_001

        item_b = FeedItem(
            feed_item_id="f_002",
            content="y",
            source="commercial_push",
            created_at=ledger.current_time,
        )
        service.inject_feed_item(item_b, ["emma"])

        view_2 = pipeline.render(self._render_ctx(service))
        digital = view_2.get_observations_by_sense(SenseType.DIGITAL)
        assert len(digital) == 1
        assert digital[0].source_id == "f_002"

    def test_reset_consumed_re_surfaces(self):
        pipeline, service, ledger = self._minimal_setup()
        item = FeedItem(
            feed_item_id="f_001",
            content="x",
            source="local_news",
            created_at=ledger.current_time,
        )
        service.inject_feed_item(item, ["emma"])
        pipeline.render(self._render_ctx(service))  # consumed
        service.reset_consumed("emma")

        view_again = pipeline.render(self._render_ctx(service))
        assert len(view_again.get_observations_by_sense(SenseType.DIGITAL)) == 1

    def test_consumed_is_per_agent(self):
        from synthetic_socio_wind_tunnel.atlas.models import Coord
        from synthetic_socio_wind_tunnel.ledger.models import EntityState

        pipeline, service, ledger = self._minimal_setup()
        ledger.set_entity(EntityState(
            entity_id="bob",
            location_id="street_a",
            position=Coord(x=1.0, y=1.0),
        ))
        item = FeedItem(
            feed_item_id="f_001",
            content="x",
            source="local_news",
            created_at=ledger.current_time,
        )
        service.inject_feed_item(item, ["emma", "bob"])

        # Emma renders, consumes her own copy
        pipeline.render(self._render_ctx(service, "emma"))
        # Bob's should still be pending
        assert service.pending_for("bob") == ("f_001",)
