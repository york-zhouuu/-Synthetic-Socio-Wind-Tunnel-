"""Tests for attention-channel data models."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from synthetic_socio_wind_tunnel.attention import (
    AttentionState,
    DigitalProfile,
    FeedItem,
    NotificationEvent,
    create_notification_event,
)
from synthetic_socio_wind_tunnel.core.errors import EventType


class TestFeedItem:

    def _make(self, **overrides) -> FeedItem:
        defaults = dict(
            feed_item_id="f_001",
            content="Sunset Bar tasting tonight",
            source="local_news",
            hyperlocal_radius=300.0,
            urgency=0.7,
            created_at=datetime(2026, 4, 20, 18, 0, 0),
        )
        defaults.update(overrides)
        return FeedItem(**defaults)

    def test_construct_basic(self):
        item = self._make()
        assert item.feed_item_id == "f_001"
        assert item.hyperlocal_radius == 300.0

    def test_frozen(self):
        item = self._make()
        with pytest.raises(ValidationError):
            item.content = "hacked"

    def test_hashable(self):
        item_a = self._make()
        item_b = self._make()
        assert hash(item_a) == hash(item_b)

    def test_negative_radius_rejected(self):
        with pytest.raises(ValidationError):
            self._make(hyperlocal_radius=-10.0)

    def test_urgency_bounds(self):
        with pytest.raises(ValidationError):
            self._make(urgency=1.5)
        with pytest.raises(ValidationError):
            self._make(urgency=-0.1)

    def test_global_item_without_radius(self):
        item = self._make(source="global_news", hyperlocal_radius=None)
        assert item.hyperlocal_radius is None


class TestDigitalProfile:

    def test_defaults(self):
        profile = DigitalProfile()
        assert profile.daily_screen_hours == 0.0
        assert profile.feed_bias == "global"
        assert profile.notification_responsiveness == 0.5
        assert profile.primary_apps == ()

    def test_negative_screen_hours_rejected(self):
        with pytest.raises(ValidationError):
            DigitalProfile(daily_screen_hours=-1.0)

    def test_responsiveness_bounds(self):
        with pytest.raises(ValidationError):
            DigitalProfile(notification_responsiveness=1.2)
        with pytest.raises(ValidationError):
            DigitalProfile(notification_responsiveness=-0.1)

    def test_frozen(self):
        profile = DigitalProfile()
        with pytest.raises(ValidationError):
            profile.feed_bias = "local"


class TestAttentionState:

    def test_defaults(self):
        state = AttentionState()
        assert state.attention_target == "physical_world"
        assert state.pending_notifications == ()

    def test_pending_is_tuple(self):
        state = AttentionState(pending_notifications=("f_001", "f_002"))
        assert isinstance(state.pending_notifications, tuple)

    def test_hashable(self):
        state_a = AttentionState(attention_target="phone_feed")
        state_b = AttentionState(attention_target="phone_feed")
        assert hash(state_a) == hash(state_b)

    def test_frozen(self):
        state = AttentionState()
        with pytest.raises(ValidationError):
            state.attention_target = "task"


class TestNotificationEvent:

    def test_factory_fills_properties(self):
        event = create_notification_event(
            feed_item_id="f_001",
            recipient_entity_id="emma",
            recipient_location_id="cafe_a",
            timestamp=datetime(2026, 4, 20, 18, 0, 0),
        )
        assert event.event_type == EventType.NOTIFICATION_RECEIVED
        assert event.properties["feed_item_id"] == "f_001"
        assert event.properties["recipient_entity_id"] == "emma"
        assert event.target_id == "emma"
        assert event.audible_range == 0.0
        assert event.visible_range == 0.0

    def test_accessors(self):
        event = create_notification_event(
            feed_item_id="f_001",
            recipient_entity_id="emma",
            recipient_location_id="cafe_a",
            timestamp=datetime(2026, 4, 20, 18, 0, 0),
        )
        assert event.feed_item_id == "f_001"
        assert event.recipient_entity_id == "emma"

    def test_roundtrip_dict(self):
        original = create_notification_event(
            feed_item_id="f_001",
            recipient_entity_id="emma",
            recipient_location_id="cafe_a",
            timestamp=datetime(2026, 4, 20, 18, 0, 0),
            origin_hack_id="hack_9",
        )
        restored = NotificationEvent.from_dict(original.to_dict())
        assert restored.event_type == original.event_type
        assert restored.properties == original.properties
        assert restored.timestamp == original.timestamp
        assert restored.source_action == original.source_action

    def test_origin_hack_optional(self):
        event = create_notification_event(
            feed_item_id="f_001",
            recipient_entity_id="emma",
            recipient_location_id="cafe_a",
            timestamp=datetime(2026, 4, 20, 18, 0, 0),
        )
        assert "origin_hack_id" not in event.properties
