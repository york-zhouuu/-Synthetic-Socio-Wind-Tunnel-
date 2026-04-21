"""Tests for AttentionService."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention import (
    AttentionService,
    DigitalProfile,
    FeedItem,
)
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState


@pytest.fixture()
def ledger() -> Ledger:
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 20, 18, 0, 0)
    for entity_id, location in [("emma", "cafe_a"), ("bob", "cafe_a"), ("chen", "street_1")]:
        ledger.set_entity(EntityState(
            entity_id=entity_id,
            location_id=location,
            position=Coord(x=0.0, y=0.0),
        ))
    return ledger


def _feed_item(source: str = "local_news", **kw) -> FeedItem:
    defaults = dict(
        feed_item_id="f_001",
        content="Sunset Bar tasting",
        source=source,
        hyperlocal_radius=300.0,
        urgency=0.7,
        created_at=datetime(2026, 4, 20, 18, 0, 0),
    )
    defaults.update(kw)
    return FeedItem(**defaults)


class TestInjection:

    def test_delivers_to_targeted_recipients(self, ledger: Ledger):
        service = AttentionService(ledger, seed=0)
        delivered = service.inject_feed_item(_feed_item(source="commercial_push"),
                                             ["emma", "bob"])
        assert len(delivered) == 2
        assert len(service.notifications_for("emma")) == 1
        assert len(service.notifications_for("bob")) == 1
        assert service.notifications_for("chen") == []

    def test_uses_recipient_location(self, ledger: Ledger):
        service = AttentionService(ledger, seed=0)
        [event] = service.inject_feed_item(_feed_item(source="commercial_push"),
                                           ["emma"])
        assert event.location_id == "cafe_a"

    def test_location_override(self, ledger: Ledger):
        service = AttentionService(ledger, seed=0)
        [event] = service.inject_feed_item(
            _feed_item(source="commercial_push"),
            ["emma"],
            recipient_locations={"emma": "park_b"},
        )
        assert event.location_id == "park_b"

    def test_missing_entity_falls_back_to_unknown(self, ledger: Ledger):
        service = AttentionService(ledger, seed=0)
        [event] = service.inject_feed_item(_feed_item(source="commercial_push"),
                                           ["nonexistent"])
        assert event.location_id == "unknown"

    def test_no_physical_propagation(self, ledger: Ledger):
        """Digital events MUST NOT touch audible_range/visible_range."""
        service = AttentionService(ledger, seed=0)
        [event] = service.inject_feed_item(_feed_item(source="commercial_push"),
                                           ["emma"])
        assert event.audible_range == 0.0
        assert event.visible_range == 0.0


class TestBiasSuppression:

    def test_global_bias_drops_local_news(self, ledger: Ledger):
        profiles = {"emma": DigitalProfile(feed_bias="global")}
        # Suppression = 1.0 → always drop local news for global-biased recipients
        service = AttentionService(ledger, profiles=profiles, seed=0,
                                   feed_bias_suppression=1.0)
        delivered = service.inject_feed_item(_feed_item(source="local_news"),
                                             ["emma"])
        assert delivered == []
        assert service.notifications_for("emma") == []
        log = service.export_feed_log()
        assert len(log) == 1
        assert log[0].delivered is False
        assert log[0].suppressed_by_bias is True

    def test_local_bias_drops_global_news(self, ledger: Ledger):
        profiles = {"emma": DigitalProfile(feed_bias="local")}
        service = AttentionService(ledger, profiles=profiles, seed=0,
                                   feed_bias_suppression=1.0)
        delivered = service.inject_feed_item(_feed_item(source="global_news"),
                                             ["emma"])
        assert delivered == []

    def test_mixed_bias_never_suppressed(self, ledger: Ledger):
        profiles = {"emma": DigitalProfile(feed_bias="mixed")}
        service = AttentionService(ledger, profiles=profiles, seed=0,
                                   feed_bias_suppression=1.0)
        assert service.inject_feed_item(_feed_item(source="local_news"),
                                        ["emma"])
        assert service.inject_feed_item(_feed_item(source="global_news"),
                                        ["emma"])

    def test_statistical_suppression_expectation(self, ledger: Ledger):
        """With suppression=0.5 and 200 trials, delivered ≈ 100."""
        profiles = {"emma": DigitalProfile(feed_bias="global")}
        service = AttentionService(ledger, profiles=profiles, seed=42,
                                   feed_bias_suppression=0.5)
        trials = 200
        for i in range(trials):
            service.inject_feed_item(_feed_item(feed_item_id=f"f_{i}",
                                                source="local_news"), ["emma"])
        delivered = len(service.notifications_for("emma"))
        # Expect ~100, allow generous window to avoid flake
        assert 70 <= delivered <= 130, delivered


class TestPending:

    def test_pending_reflects_delivered(self, ledger: Ledger):
        service = AttentionService(ledger, seed=0)
        service.inject_feed_item(_feed_item(feed_item_id="f_001",
                                            source="commercial_push"), ["emma"])
        service.inject_feed_item(_feed_item(feed_item_id="f_002",
                                            source="commercial_push"), ["emma"])
        pending = service.pending_for("emma")
        assert set(pending) == {"f_001", "f_002"}

    def test_since_filter(self, ledger: Ledger):
        service = AttentionService(ledger, seed=0)
        service.inject_feed_item(_feed_item(feed_item_id="f_001",
                                            source="commercial_push"), ["emma"])
        later = ledger.current_time + timedelta(hours=2)
        ledger.current_time = later
        service.inject_feed_item(_feed_item(feed_item_id="f_002",
                                            source="commercial_push"), ["emma"])
        recent = service.notifications_for("emma", since=later)
        assert {e.feed_item_id for e in recent} == {"f_002"}


class TestLogExport:

    def test_log_captures_both_delivered_and_suppressed(self, ledger: Ledger):
        profiles = {"emma": DigitalProfile(feed_bias="global")}
        service = AttentionService(ledger, profiles=profiles, seed=0,
                                   feed_bias_suppression=1.0)
        service.inject_feed_item(_feed_item(source="local_news"), ["emma"])
        service.inject_feed_item(_feed_item(feed_item_id="f_002",
                                            source="commercial_push"), ["emma"])
        log = service.export_feed_log()
        assert len(log) == 2
        suppressed = [r for r in log if r.suppressed_by_bias]
        delivered = [r for r in log if r.delivered]
        assert len(suppressed) == 1
        assert len(delivered) == 1

    def test_log_time_window(self, ledger: Ledger):
        service = AttentionService(ledger, seed=0)
        t0 = ledger.current_time
        service.inject_feed_item(_feed_item(feed_item_id="f_001",
                                            source="commercial_push"), ["emma"])
        t1 = t0 + timedelta(hours=1)
        ledger.current_time = t1
        service.inject_feed_item(_feed_item(feed_item_id="f_002",
                                            source="commercial_push"), ["emma"])
        window = service.export_feed_log(since=t1)
        assert len(window) == 1
        assert window[0].feed_item_id == "f_002"
