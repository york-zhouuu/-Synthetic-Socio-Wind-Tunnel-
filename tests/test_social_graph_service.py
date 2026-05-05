"""Tests for SocialGraphService — accumulation, formula, queries."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.social_graph import (
    STRONG_TIE_THRESHOLD,
    SocialGraphService,
    Tie,
    WEAK_TIE_THRESHOLD,
)


class TestRecordEncounter:

    def test_first_encounter_creates_tie(self):
        g = SocialGraphService(K=10)
        tie = g.record_encounter("emma", "linda", tick=10, day_index=0)
        assert tie.agent_a == "emma"
        assert tie.agent_b == "linda"
        assert tie.encounter_count == 1
        assert tie.first_seen_tick == 10
        assert tie.last_seen_tick == 10
        assert tie.first_seen_day == 0
        assert tie.strength == pytest.approx(1 / 11, abs=1e-3)

    def test_canonical_ordering_normalizes_input(self):
        g = SocialGraphService(K=10)
        tie = g.record_encounter("linda", "emma", tick=10)
        assert tie.agent_a == "emma"
        assert tie.agent_b == "linda"
        # subsequent get with reverse order returns same tie
        assert g.get_tie("linda", "emma") is tie
        assert g.get_tie("emma", "linda") is tie

    def test_different_ticks_increment(self):
        g = SocialGraphService(K=10)
        g.record_encounter("emma", "linda", tick=10)
        g.record_encounter("emma", "linda", tick=20)
        g.record_encounter("emma", "linda", tick=30)
        tie = g.get_tie("emma", "linda")
        assert tie.encounter_count == 3
        assert tie.first_seen_tick == 10
        assert tie.last_seen_tick == 30

    def test_same_tick_idempotent(self):
        g = SocialGraphService(K=10)
        g.record_encounter("emma", "linda", tick=10)
        g.record_encounter("emma", "linda", tick=10)
        g.record_encounter("emma", "linda", tick=10)
        tie = g.get_tie("emma", "linda")
        assert tie.encounter_count == 1, "same tick same pair should not double"

    def test_same_tick_different_pairs_independent(self):
        g = SocialGraphService(K=10)
        g.record_encounter("emma", "linda", tick=10)
        g.record_encounter("emma", "john", tick=10)
        assert g.get_tie("emma", "linda").encounter_count == 1
        assert g.get_tie("emma", "john").encounter_count == 1


class TestStrengthFormula:

    @pytest.mark.parametrize("count,expected", [
        (1, 0.091),
        (5, 0.333),
        (10, 0.500),
        (30, 0.750),
    ])
    def test_strength_at_count(self, count, expected):
        g = SocialGraphService(K=10)
        for tick in range(count):
            g.record_encounter("a", "b", tick=tick)
        tie = g.get_tie("a", "b")
        assert tie.encounter_count == count
        assert tie.strength == pytest.approx(expected, abs=1e-3)

    def test_K_can_be_customized(self):
        g = SocialGraphService(K=5)
        for tick in range(5):
            g.record_encounter("a", "b", tick=tick)
        tie = g.get_tie("a", "b")
        # 5 / (5+5) = 0.5
        assert tie.strength == pytest.approx(0.5, abs=1e-3)

    def test_K_zero_rejected(self):
        with pytest.raises(ValueError):
            SocialGraphService(K=0)


class TestQueries:

    def _populate(self, g: SocialGraphService) -> None:
        # emma <-> 4 neighbours with various encounter_counts
        for tick in range(0):  # 0 encounters with sam
            g.record_encounter("emma", "sam", tick=tick)
        for tick in range(2):  # 2 with bob → strength 0.167
            g.record_encounter("emma", "bob", tick=tick)
        for tick in range(10):  # 10 with linda → strength 0.500
            g.record_encounter("emma", "linda", tick=tick)
        for tick in range(30):  # 30 with john → strength 0.750
            g.record_encounter("emma", "john", tick=tick)

    def test_get_tie_unknown_pair_returns_none(self):
        g = SocialGraphService(K=10)
        assert g.get_tie("emma", "linda") is None

    def test_get_tie_same_agent_returns_none(self):
        g = SocialGraphService(K=10)
        assert g.get_tie("emma", "emma") is None

    def test_ties_for_returns_all_involving_agent(self):
        g = SocialGraphService(K=10)
        self._populate(g)
        ties = g.ties_for("emma")
        assert len(ties) == 3  # bob, linda, john
        partners = {t.agent_a if t.agent_b == "emma" else t.agent_b for t in ties}
        assert partners == {"bob", "linda", "john"}

    def test_ties_for_returns_empty_for_unknown(self):
        g = SocialGraphService(K=10)
        assert g.ties_for("nobody") == []

    def test_familiar_with_default_threshold(self):
        g = SocialGraphService(K=10)
        self._populate(g)
        familiar = g.familiar_with("emma")
        # bob (0.167) > 0.1 ✓; linda (0.500) > 0.1 ✓; john (0.750) > 0.1 ✓
        assert familiar == {"bob", "linda", "john"}

    def test_familiar_with_custom_threshold(self):
        g = SocialGraphService(K=10)
        self._populate(g)
        # threshold=0.4 keeps only linda (0.500) and john (0.750)
        familiar = g.familiar_with("emma", threshold=0.4)
        assert familiar == {"linda", "john"}

    def test_weak_vs_strong_classification(self):
        g = SocialGraphService(K=10)
        self._populate(g)
        weak = {t.agent_b if t.agent_a == "emma" else t.agent_a
                for t in g.weak_ties("emma")}
        strong = {t.agent_b if t.agent_a == "emma" else t.agent_a
                  for t in g.strong_ties("emma")}
        # bob (0.167) ∈ [0.1, 0.5) → weak
        # linda (0.500) >= 0.5 → strong
        # john (0.750) >= 0.5 → strong
        assert weak == {"bob"}
        assert strong == {"linda", "john"}

    def test_no_historical_backfill(self):
        """Service has no memory — only counts what record_encounter receives."""
        g = SocialGraphService(K=10)
        # never call record_encounter
        assert g.all_ties() == []
        assert g.total_count() == 0


class TestMetricHelpers:

    def test_counts(self):
        g = SocialGraphService(K=10)
        # 1 weak + 2 strong + 1 below-weak
        for t in range(2):  g.record_encounter("a", "b", t)  # weak
        for t in range(15): g.record_encounter("a", "c", t)  # strong
        for t in range(20): g.record_encounter("a", "d", t)  # strong
        # 1 below-weak (count=1, strength 0.091 < 0.1)
        g.record_encounter("a", "e", 0)

        assert g.total_count() == 4
        assert g.weak_count() == 1
        assert g.strong_count() == 2

    def test_new_ties_on_day(self):
        g = SocialGraphService(K=10)
        g.record_encounter("a", "b", tick=0, day_index=0)
        g.record_encounter("a", "c", tick=288, day_index=1)
        g.record_encounter("a", "d", tick=288, day_index=1)
        g.record_encounter("a", "b", tick=288, day_index=1)  # repeat, not new on day 1

        assert g.new_ties_on_day(0) == 1
        assert g.new_ties_on_day(1) == 2
        assert g.new_ties_on_day(2) == 0
