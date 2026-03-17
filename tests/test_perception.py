"""Tests for the Perception module."""

import pytest
from synthetic_socio_wind_tunnel.perception.models import (
    ObserverContext,
    SubjectiveView,
    Observation,
    SenseType,
)
from synthetic_socio_wind_tunnel.perception.pipeline import PerceptionPipeline
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.ledger.models import ClueState


class TestObserverContext:
    """Tests for ObserverContext model."""

    def test_default_skills(self):
        ctx = ObserverContext(
            entity_id="alice",
            position=Coord(x=5, y=5),
        )
        assert ctx.perception_skill == 0.5
        assert ctx.investigation_skill == 0.5
        assert ctx.guilt_level == 0.0

    def test_guilty_observer(self):
        ctx = ObserverContext(
            entity_id="linda",
            position=Coord(x=5, y=5),
            emotional_state={"guilt": 0.9},
            secrets=["I did it"],
        )
        assert ctx.guilt_level == 0.9
        assert "I did it" in ctx.secrets


class TestSubjectiveView:
    """Tests for SubjectiveView model."""

    def test_empty_view(self):
        view = SubjectiveView(
            observer_id="test",
            location_id="test_room",
            location_name="Test Room",
        )
        assert view.location_id == "test_room"
        assert len(view.observations) == 0
        assert len(view.entities_seen) == 0

    def test_get_notable_observations(self):
        view = SubjectiveView(
            observer_id="test",
            location_id="test_room",
            location_name="Test Room",
            observations=[
                Observation(
                    sense=SenseType.VISUAL,
                    source_id="item1",
                    source_type="item",
                    is_notable=True,
                ),
                Observation(
                    sense=SenseType.VISUAL,
                    source_id="item2",
                    source_type="item",
                    is_notable=False,
                ),
            ],
        )
        notable = view.get_notable_observations()
        assert len(notable) == 1
        assert notable[0].source_id == "item1"


class TestPerceptionPipeline:
    """Tests for PerceptionPipeline."""

    def test_render_basic(self, perception, atlas):
        center = atlas.get_center("test_building")
        observer = ObserverContext(
            entity_id="alice",
            position=center,
        )

        view = perception.render(observer)

        assert view is not None
        assert view.observer_id == "alice"
        assert view.narrative != ""

    def test_different_observers_different_views(self, perception, atlas, ledger, simulation):
        center = atlas.get_center("test_room")

        # Place a character and item
        simulation.move_entity("bob", "test_room")
        simulation.place_item(
            "hidden_note", "Hidden Note", "test_room",
            is_hidden=True, discovery_skill=0.7,
        )

        # Inject a clue
        clue = ClueState(
            clue_id="evidence",
            location_id="test_room",
            reveals=["Important fact"],
            min_skill=0.6,
        )
        ledger.set_clue(clue)

        # Skilled observer
        skilled = ObserverContext(
            entity_id="detective",
            position=center,
            skills={"investigation": 0.9, "perception": 0.9},
        )

        # Unskilled observer
        unskilled = ObserverContext(
            entity_id="visitor",
            position=center,
            skills={"investigation": 0.2, "perception": 0.3},
        )

        skilled_view = perception.render(skilled)
        unskilled_view = perception.render(unskilled)

        # Both should see Bob
        assert "bob" in skilled_view.entities_seen
        assert "bob" in unskilled_view.entities_seen

        # Only skilled should find the clue
        assert "evidence" in skilled_view.clues_found
        assert "evidence" not in unskilled_view.clues_found

    def test_compare_views(self, perception, atlas):
        center = atlas.get_center("test_building")

        emma = ObserverContext(
            entity_id="emma",
            position=center,
            skills={"investigation": 0.9},
        )
        linda = ObserverContext(
            entity_id="linda",
            position=center,
            skills={"investigation": 0.3},
            emotional_state={"guilt": 0.8},
        )

        comparison = perception.compare(emma, linda)

        assert comparison["same_location"]


class TestObservation:
    """Tests for Observation model."""

    def test_entity_observation(self):
        obs = Observation(
            sense=SenseType.VISUAL,
            source_id="bob",
            source_type="entity",
            distance=5.0,
            is_notable=True,
        )
        assert obs.sense == SenseType.VISUAL
        assert obs.is_notable

    def test_item_observation(self):
        obs = Observation(
            sense=SenseType.VISUAL,
            source_id="book",
            source_type="item",
            distance=2.0,
            tags=["evidence"],
        )
        assert "evidence" in obs.tags


class TestRashomonEffect:
    """Tests demonstrating the Rashomon effect."""

    def test_same_location_different_narratives(self, perception, atlas, ledger, simulation):
        """
        The core Rashomon test: same physical space,
        different subjective experiences.
        """
        center = atlas.get_center("test_room")

        # Setup: add evidence
        simulation.place_item("tea_cup", "Tea Cup", "test_room")

        clue = ClueState(
            clue_id="poison_residue",
            location_id="test_room",
            reveals=["The tea was poisoned"],
            min_skill=0.7,
        )
        ledger.set_clue(clue)

        # Detective perspective
        detective = ObserverContext(
            entity_id="emma",
            position=center,
            skills={"investigation": 0.9},
            knowledge=["Victim drank tea"],
            looking_for=["evidence", "tea"],
            attention=0.9,
        )

        # Guilty party perspective
        guilty = ObserverContext(
            entity_id="linda",
            position=center,
            skills={"investigation": 0.3},
            emotional_state={"guilt": 0.9},
            secrets=["I poisoned the tea"],
        )

        # Innocent bystander perspective
        bystander = ObserverContext(
            entity_id="visitor",
            position=center,
            skills={"investigation": 0.2},
        )

        detective_view = perception.render(detective)
        guilty_view = perception.render(guilty)
        bystander_view = perception.render(bystander)

        # All see the same location
        assert detective_view.location_id == guilty_view.location_id == bystander_view.location_id

        # Detective finds the clue
        assert "poison_residue" in detective_view.clues_found

        # Guilty party doesn't find clue (low skill)
        assert "poison_residue" not in guilty_view.clues_found

        # Bystander doesn't find clue
        assert "poison_residue" not in bystander_view.clues_found

        # All narratives should be generated
        assert detective_view.narrative != ""
        assert guilty_view.narrative != ""
        assert bystander_view.narrative != ""
