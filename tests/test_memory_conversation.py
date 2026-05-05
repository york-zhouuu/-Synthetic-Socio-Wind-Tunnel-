"""Tests for MemoryService ↔ ConversationService integration."""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention import AttentionService, FeedItem
from synthetic_socio_wind_tunnel.conversation import ConversationService
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.memory.service import MemoryService
from synthetic_socio_wind_tunnel.orchestrator.models import (
    EncounterCandidate,
    TickResult,
)
from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


def _profile(agent_id: str, extraversion: float = 0.5) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id, name=agent_id.title(), age=30, occupation="x",
        household="single", home_location="home",
        personality=PersonalityTraits(extraversion=extraversion),
    )


def _runtime(agent_id: str, **kw) -> AgentRuntime:
    return AgentRuntime(profile=_profile(agent_id, **kw), current_location="home")


def _tick(tick: int, day: int = 0, encs: list[tuple[str, str]] = ()) -> TickResult:
    return TickResult(
        tick_index=tick, day_index=day,
        simulated_time=datetime(2026, 5, 5),
        commits=(),
        encounter_candidates=tuple(
            EncounterCandidate(
                agent_a=a, agent_b=b, shared_locations=("cafe",), tick=tick,
            )
            for a, b in encs
        ),
    )


class TestConstructorValidation:

    def test_conversation_without_social_graph_rejected(self):
        with pytest.raises(ValueError, match="social_graph"):
            MemoryService(
                conversation=ConversationService(seed=42),
                social_graph=None,
            )

    def test_conversation_with_social_graph_ok(self):
        # Should not raise
        m = MemoryService(
            conversation=ConversationService(seed=42),
            social_graph=SocialGraphService(K=10),
        )
        assert m._conversation is not None


class TestSalienceFromFeed:

    def test_hyperlocal_high_salience(self):
        feed = FeedItem(
            feed_item_id="f1", content="本街市集",
            source="local_news", urgency=0.6,
            created_at=datetime(2026, 5, 5),
            hyperlocal_radius=500.0,
        )
        assert MemoryService._salience_from_feed(feed) == 0.8

    def test_global_distraction_low_salience(self):
        feed = FeedItem(
            feed_item_id="f2", content="global news",
            source="global_news", urgency=0.5,
            created_at=datetime(2026, 5, 5),
            category="global_distraction",
        )
        assert MemoryService._salience_from_feed(feed) == 0.3

    def test_commercial_default(self):
        feed = FeedItem(
            feed_item_id="f3", content="买买买",
            source="commercial_push", urgency=0.4,
            created_at=datetime(2026, 5, 5),
            category="commercial_push",
        )
        assert MemoryService._salience_from_feed(feed) == 0.5


class TestPushOriginInjection:

    def _setup(self):
        ledger = Ledger()
        ledger.current_time = datetime(2026, 5, 5)
        for aid in ("emma", "linda"):
            ledger.set_entity(EntityState(
                entity_id=aid, position=Coord(x=0, y=0), location_id="home",
            ))
        attention = AttentionService(ledger=ledger, seed=42)
        graph = SocialGraphService(K=10)
        conv = ConversationService(seed=42)
        memory = MemoryService(
            attention_service=attention,
            social_graph=graph,
            conversation=conv,
        )
        return ledger, attention, graph, conv, memory

    def test_push_creates_information_origin(self):
        _, attention, _, conv, memory = self._setup()
        # Inject a hyperlocal push to emma
        feed = FeedItem(
            feed_item_id="f1", content="本街周六市集",
            source="local_news", urgency=0.6,
            created_at=datetime(2026, 5, 5),
            hyperlocal_radius=500.0,
        )
        attention.inject_feed_item(feed, ["emma"])

        agents = {
            "emma": _runtime("emma"), "linda": _runtime("linda"),
        }
        memory.process_tick(_tick(10), agents, planner=None)

        # emma should now know one info
        known = conv.info_known_by("emma")
        assert len(known) == 1
        info_id = next(iter(known))
        info = conv._infos[info_id]  # type: ignore[attr-defined]
        assert info.salience == 0.8  # hyperlocal
        assert info.source_feed_item_id == "f1"
        assert info.origin_agent_id == "emma"
        assert info.origin_day_index == 0

    def test_no_conversation_no_origin(self):
        ledger = Ledger()
        ledger.current_time = datetime(2026, 5, 5)
        for aid in ("emma",):
            ledger.set_entity(EntityState(
                entity_id=aid, position=Coord(x=0, y=0), location_id="home",
            ))
        attention = AttentionService(ledger=ledger, seed=42)
        memory = MemoryService(attention_service=attention)  # no conv/graph
        # Should not crash; no Information should be created (no conv to record on)
        feed = FeedItem(
            feed_item_id="f1", content="x", source="local_news",
            urgency=0.5, created_at=datetime(2026, 5, 5),
        )
        attention.inject_feed_item(feed, ["emma"])
        memory.process_tick(
            _tick(10), {"emma": _runtime("emma")}, planner=None,
        )
        # MemoryEvent still recorded
        assert any(e.kind == "notification" for e in memory.all_for("emma"))


class TestPropagationOnEncounters:

    def test_info_can_propagate_via_encounter(self):
        """Force high-salience push + strong tie + extraverted agents → info should reach linda eventually."""
        ledger = Ledger()
        ledger.current_time = datetime(2026, 5, 5)
        for aid in ("emma", "linda"):
            ledger.set_entity(EntityState(
                entity_id=aid, position=Coord(x=0, y=0), location_id="home",
            ))
        attention = AttentionService(ledger=ledger, seed=42)
        graph = SocialGraphService(K=10)
        # Pre-build strong tie via 30 prior encounters → strength ~ 0.75
        for tick in range(30):
            graph.record_encounter("emma", "linda", tick=tick)

        conv = ConversationService(seed=42)
        memory = MemoryService(
            attention_service=attention, social_graph=graph,
            conversation=conv,
        )
        feed = FeedItem(
            feed_item_id="f1", content="本街市集",
            source="local_news", urgency=0.6,
            created_at=datetime(2026, 5, 5),
            hyperlocal_radius=500.0,
        )
        attention.inject_feed_item(feed, ["emma"])

        agents = {
            "emma": _runtime("emma", extraversion=0.9),
            "linda": _runtime("linda", extraversion=0.9),
        }

        # Tick 10: emma ingests push (origin)
        memory.process_tick(_tick(10), agents, planner=None)
        assert "info_f1" in conv.info_known_by("emma")
        # Tick 20-50: emma <-> linda multiple encounters
        spread = False
        for tick in range(20, 100, 5):
            memory.process_tick(_tick(tick, encs=[("emma", "linda")]), agents, planner=None)
            if "info_f1" in conv.info_known_by("linda"):
                spread = True
                break
        assert spread, (
            "with strong tie + extraverted + hyperlocal, info should propagate "
            "within 16 encounters"
        )
        prop = conv.get_propagation("info_f1")
        assert prop.hops_at["linda"] == 1
