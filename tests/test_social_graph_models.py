"""Tests for social_graph.models — Tie immutability + canonical pair."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.social_graph.models import Tie, canonical_pair


class TestCanonicalPair:

    def test_already_sorted(self):
        assert canonical_pair("alice", "bob") == ("alice", "bob")

    def test_reverse_sort(self):
        assert canonical_pair("bob", "alice") == ("alice", "bob")

    def test_same_agent_rejected(self):
        with pytest.raises(ValueError, match="cannot form tie"):
            canonical_pair("emma", "emma")


class TestTie:

    def test_construct_canonical_ok(self):
        t = Tie(
            agent_a="emma", agent_b="linda",
            encounter_count=1, strength=0.091,
            first_seen_tick=10, last_seen_tick=10, first_seen_day=0,
        )
        assert t.agent_a == "emma"
        assert t.agent_b == "linda"

    def test_construct_non_canonical_raises(self):
        with pytest.raises(ValueError, match="lex"):
            Tie(
                agent_a="linda", agent_b="emma",
                encounter_count=1, strength=0.091,
                first_seen_tick=10, last_seen_tick=10, first_seen_day=0,
            )

    def test_construct_zero_encounter_raises(self):
        with pytest.raises(ValueError, match="encounter_count"):
            Tie(
                agent_a="emma", agent_b="linda",
                encounter_count=0, strength=0.0,
                first_seen_tick=10, last_seen_tick=10, first_seen_day=0,
            )

    def test_frozen_cannot_mutate(self):
        t = Tie(
            agent_a="emma", agent_b="linda",
            encounter_count=1, strength=0.091,
            first_seen_tick=10, last_seen_tick=10, first_seen_day=0,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            t.encounter_count = 5  # type: ignore[misc]
