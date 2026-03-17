"""Tests for the Ledger module."""

import pytest
from datetime import datetime

from synthetic_socio_wind_tunnel.ledger.models import (
    LedgerData,
    EntityState,
    ItemState,
    ClueState,
    ContainerState,
    Weather,
    TimeOfDay,
)
from synthetic_socio_wind_tunnel.ledger.service import Ledger
from synthetic_socio_wind_tunnel.atlas.models import Coord


class TestLedgerData:
    """Tests for LedgerData model."""

    def test_default_values(self):
        data = LedgerData()
        assert data.weather == Weather.CLEAR
        assert data.time_of_day == TimeOfDay.MORNING
        assert len(data.entities) == 0


class TestLedgerService:
    """Tests for Ledger service."""

    def test_get_entity(self, ledger):
        state = EntityState(
            entity_id="alice",
            location_id="room1",
            position=Coord(x=0, y=0),
        )
        ledger.set_entity(state)

        retrieved = ledger.get_entity("alice")
        assert retrieved is not None
        assert retrieved.entity_id == "alice"
        assert retrieved.location_id == "room1"

    def test_entities_at_location(self, ledger):
        ledger.set_entity(EntityState(
            entity_id="alice",
            location_id="room1",
            position=Coord(x=0, y=0),
        ))
        ledger.set_entity(EntityState(
            entity_id="bob",
            location_id="room1",
            position=Coord(x=1, y=1),
        ))
        ledger.set_entity(EntityState(
            entity_id="charlie",
            location_id="room2",
            position=Coord(x=10, y=10),
        ))

        room1_entities = list(ledger.entities_at("room1"))
        assert len(room1_entities) == 2
        entity_ids = [e.entity_id for e in room1_entities]
        assert "alice" in entity_ids
        assert "bob" in entity_ids
        assert "charlie" not in entity_ids

    def test_items_at_location(self, ledger):
        ledger.set_item(ItemState(
            item_id="book",
            name="Book",
            location_id="room1",
        ))
        ledger.set_item(ItemState(
            item_id="pen",
            name="Pen",
            location_id="room1",
        ))
        ledger.set_item(ItemState(
            item_id="key",
            name="Key",
            location_id="room2",
        ))

        room1_items = list(ledger.items_at("room1"))
        assert len(room1_items) == 2
        item_ids = [i.item_id for i in room1_items]
        assert "book" in item_ids
        assert "pen" in item_ids

    def test_time_updates_time_of_day(self, ledger):
        morning = datetime(2024, 1, 1, 9, 0)
        ledger.current_time = morning
        assert ledger.time_of_day == TimeOfDay.MORNING

        night = datetime(2024, 1, 1, 23, 0)
        ledger.current_time = night
        assert ledger.time_of_day == TimeOfDay.NIGHT

    def test_set_weather(self, ledger):
        ledger.weather = Weather.RAIN
        assert ledger.weather == Weather.RAIN

    def test_clue_discovery(self, ledger):
        clue = ClueState(
            clue_id="test_clue",
            location_id="room1",
            reveals=["Secret fact"],
            min_skill=0.5,
        )
        ledger.set_clue(clue)

        # Check undiscovered clues
        undiscovered = list(ledger.undiscovered_clues_at("room1"))
        assert len(undiscovered) == 1

        # Discover the clue
        success = ledger.mark_clue_discovered("test_clue", "alice")
        assert success

        # Try to discover again - should fail
        success = ledger.mark_clue_discovered("test_clue", "bob")
        assert not success

        # Check undiscovered clues again
        undiscovered = list(ledger.undiscovered_clues_at("room1"))
        assert len(undiscovered) == 0

    def test_plot_tags(self, ledger):
        ledger.add_tag("room1", "crime_scene")
        assert ledger.has_tag("room1", "crime_scene")

        ledger.remove_tag("room1", "crime_scene")
        assert not ledger.has_tag("room1", "crime_scene")

    def test_container_state(self, ledger):
        # Get or create
        state = ledger.get_or_create_container_state("desk")
        assert state.container_id == "desk"
        assert not state.is_open
        assert not state.contents_collapsed

        # Record examination
        ledger.record_examination("desk", "alice", 0.7)
        state = ledger.get_container_state("desk")
        assert "alice" in state.examined_by
        assert state.examination_depth["alice"] == 0.7

        # Mark collapsed
        ledger.mark_container_collapsed("desk", "alice")
        assert ledger.is_container_collapsed("desk")

    def test_items_in_container(self, ledger):
        ledger.set_item(ItemState(
            item_id="pen",
            name="Pen",
            container_id="desk",
        ))
        ledger.set_item(ItemState(
            item_id="paper",
            name="Paper",
            container_id="desk",
        ))
        ledger.set_item(ItemState(
            item_id="book",
            name="Book",
            location_id="room1",
        ))

        desk_items = list(ledger.items_in("desk"))
        assert len(desk_items) == 2

        count = ledger.count_items_in("desk")
        assert count == 2


class TestEntityState:
    """Tests for EntityState model."""

    def test_basic_state(self):
        state = EntityState(
            entity_id="alice",
            location_id="room1",
            position=Coord(x=5, y=5),
            activity="reading",
        )
        assert state.entity_id == "alice"
        assert state.activity == "reading"


class TestItemState:
    """Tests for ItemState model."""

    def test_hidden_item(self):
        item = ItemState(
            item_id="secret_letter",
            name="Secret Letter",
            location_id="desk",
            is_hidden=True,
            discovery_skill=0.8,
        )
        assert item.is_hidden
        assert item.discovery_skill == 0.8
