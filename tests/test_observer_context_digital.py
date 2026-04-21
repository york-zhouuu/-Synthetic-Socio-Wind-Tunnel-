"""Tests for AgentRuntime → ObserverContext.digital_state composition."""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention import (
    AttentionService,
    DigitalProfile,
    FeedItem,
)
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.perception.models import (
    ObserverContext,
    SenseType,
    SubjectiveView,
    Observation,
)


@pytest.fixture()
def profile() -> AgentProfile:
    return AgentProfile(
        agent_id="emma",
        name="Emma",
        age=30,
        occupation="writer",
        household="single",
        home_location="apt_a",
        digital=DigitalProfile(
            daily_screen_hours=4.0,
            feed_bias="mixed",
            notification_responsiveness=0.8,
        ),
    )


@pytest.fixture()
def ledger() -> Ledger:
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 20, 18, 0, 0)
    ledger.set_entity(EntityState(
        entity_id="emma",
        location_id="cafe_a",
        position=Coord(x=0.0, y=0.0),
    ))
    return ledger


class TestDefault:

    def test_no_attention_service_yields_no_digital_state(self, profile: AgentProfile):
        runtime = AgentRuntime(profile=profile, current_location="cafe_a")
        ctx_dict = runtime.build_observer_context()
        assert "digital_state" not in ctx_dict
        ctx = ObserverContext(position=Coord(x=0, y=0), **ctx_dict)
        assert ctx.digital_state is None

    def test_observer_context_default_digital_state_none(self):
        """Direct ObserverContext construction without digital_state still works."""
        ctx = ObserverContext(entity_id="x", position=Coord(x=0, y=0))
        assert ctx.digital_state is None


class TestWithAttentionService:

    def test_pending_propagates_to_digital_state(self, profile: AgentProfile,
                                                  ledger: Ledger):
        service = AttentionService(ledger, seed=0)
        runtime = AgentRuntime(
            profile=profile,
            current_location="cafe_a",
            attention_service=service,
        )
        item = FeedItem(
            feed_item_id="f_001",
            content="...",
            source="commercial_push",
            created_at=ledger.current_time,
        )
        service.inject_feed_item(item, ["emma"])

        ctx_dict = runtime.build_observer_context()
        assert "digital_state" in ctx_dict
        assert ctx_dict["digital_state"].pending_notifications == ("f_001",)

    def test_empty_pending_is_empty_tuple(self, profile: AgentProfile,
                                           ledger: Ledger):
        service = AttentionService(ledger, seed=0)
        runtime = AgentRuntime(
            profile=profile,
            current_location="cafe_a",
            attention_service=service,
        )
        ctx_dict = runtime.build_observer_context()
        assert ctx_dict["digital_state"].pending_notifications == ()

    def test_screen_time_hours_from_profile(self, profile: AgentProfile,
                                             ledger: Ledger):
        service = AttentionService(ledger, seed=0)
        runtime = AgentRuntime(
            profile=profile,
            current_location="cafe_a",
            attention_service=service,
        )
        ctx_dict = runtime.build_observer_context()
        assert ctx_dict["digital_state"].screen_time_hours_today == 4.0


class TestSenseTypeDigitalAndHelper:

    def test_sense_type_digital_exists(self):
        assert SenseType.DIGITAL.value == "digital"

    def test_get_observations_by_sense_filters(self):
        view = SubjectiveView(
            observer_id="emma",
            location_id="cafe_a",
            location_name="Café A",
            observations=[
                Observation(sense=SenseType.VISUAL, source_id="v1", source_type="entity"),
                Observation(sense=SenseType.DIGITAL, source_id="f_001", source_type="feed_item"),
                Observation(sense=SenseType.AUDITORY, source_id="a1", source_type="ambient"),
            ],
        )
        digital = view.get_observations_by_sense(SenseType.DIGITAL)
        assert len(digital) == 1
        assert digital[0].source_id == "f_001"
