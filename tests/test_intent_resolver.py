"""Tests for IntentResolver conflict resolution (lexicographic)."""

from __future__ import annotations

from synthetic_socio_wind_tunnel.agent.intent import (
    MoveIntent,
    OpenDoorIntent,
    PickupIntent,
    UnlockIntent,
    WaitIntent,
)
from synthetic_socio_wind_tunnel.orchestrator.intent_resolver import IntentResolver


class TestNonExclusivePath:

    def test_all_moves_commit(self):
        resolver = IntentResolver(seed=0)
        pool = {
            "alpha": MoveIntent(to_location="cafe_a"),
            "beta": MoveIntent(to_location="cafe_a"),
            "chen": MoveIntent(to_location="library"),
        }
        decisions = resolver.resolve(pool)
        assert all(d.status == "commit" for d in decisions)
        assert [d.agent_id for d in decisions] == ["alpha", "beta", "chen"]

    def test_wait_commits(self):
        resolver = IntentResolver()
        pool = {"alpha": WaitIntent(reason="at_destination")}
        decisions = resolver.resolve(pool)
        assert decisions[0].status == "commit"


class TestExclusiveConflict:

    def test_two_pickup_same_item_alpha_wins(self):
        resolver = IntentResolver()
        pool = {
            "alpha": PickupIntent(item_id="umbrella_01"),
            "beta": PickupIntent(item_id="umbrella_01"),
        }
        decisions = resolver.resolve(pool)
        by_id = {d.agent_id: d for d in decisions}
        assert by_id["alpha"].status == "commit"
        assert by_id["beta"].status == "rejected"
        assert "alpha" in by_id["beta"].reason

    def test_three_open_same_door_lex_order(self):
        resolver = IntentResolver()
        pool = {
            "chen": OpenDoorIntent(door_id="door_main"),
            "alpha": OpenDoorIntent(door_id="door_main"),
            "beta": OpenDoorIntent(door_id="door_main"),
        }
        decisions = resolver.resolve(pool)
        by_id = {d.agent_id: d for d in decisions}
        assert by_id["alpha"].status == "commit"  # alpha wins (lex)
        assert by_id["beta"].status == "rejected"
        assert by_id["chen"].status == "rejected"

    def test_different_doors_no_conflict(self):
        resolver = IntentResolver()
        pool = {
            "alpha": OpenDoorIntent(door_id="door_a"),
            "beta": OpenDoorIntent(door_id="door_b"),
        }
        decisions = resolver.resolve(pool)
        assert all(d.status == "commit" for d in decisions)

    def test_unlock_with_different_keys_still_conflicts_on_door(self):
        resolver = IntentResolver()
        pool = {
            "alpha": UnlockIntent(door_id="door_main", key_id="key_1"),
            "beta": UnlockIntent(door_id="door_main", key_id="key_2"),
        }
        decisions = resolver.resolve(pool)
        by_id = {d.agent_id: d for d in decisions}
        assert by_id["alpha"].status == "commit"
        assert by_id["beta"].status == "rejected"


class TestMixed:

    def test_move_and_pickup_mix(self):
        """Move agents commit; pickup conflict resolves separately."""
        resolver = IntentResolver()
        pool = {
            "alpha": PickupIntent(item_id="umbrella_01"),
            "beta": MoveIntent(to_location="cafe_a"),
            "chen": PickupIntent(item_id="umbrella_01"),
        }
        decisions = resolver.resolve(pool)
        by_id = {d.agent_id: d for d in decisions}
        assert by_id["alpha"].status == "commit"  # pickup winner
        assert by_id["beta"].status == "commit"   # move non-exclusive
        assert by_id["chen"].status == "rejected"  # pickup loser


class TestDeterminism:

    def test_same_pool_same_result(self):
        resolver = IntentResolver(seed=0)
        pool = {
            "alpha": PickupIntent(item_id="x"),
            "beta": PickupIntent(item_id="x"),
        }
        d1 = resolver.resolve(pool)
        d2 = resolver.resolve(pool)
        assert [(d.agent_id, d.status) for d in d1] == [(d.agent_id, d.status) for d in d2]
