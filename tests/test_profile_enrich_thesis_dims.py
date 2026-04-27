"""
Thesis-direct slice verifications for agent-profile-enrich.

These tests exist as **prerequisite checks for downstream rival-hypothesis
analysis**: rooted-vs-floating slicing only works if the population
sample produces non-trivial subpopulations on each thesis-direct dimension.
A 1000-agent sample MUST contain enough agents in each cohort for
statistical comparison.
"""

from __future__ import annotations

from collections import Counter

from synthetic_socio_wind_tunnel.agent import (
    LANE_COVE_PROFILE,
    sample_population,
)


_AGENTS = sample_population(LANE_COVE_PROFILE, seed=42)
_N = len(_AGENTS)


class TestSubpopulationSize:
    """Each thesis-direct cohort must have enough agents for statistical compare."""

    def test_high_vs_low_unpaid_child_care(self):
        """High care_hours (15_29 + 30plus) vs low (none + 1_14)."""
        counts = Counter(a.unpaid_child_care_hours for a in _AGENTS)
        high = counts.get("15_29", 0) + counts.get("30plus", 0)
        low = counts.get("none", 0) + counts.get("1_14", 0)
        assert high >= 100, f"high care_hours cohort {high} < 100"
        assert low >= 100, f"low care_hours cohort {low} < 100"

    def test_high_vs_low_unpaid_domestic(self):
        counts = Counter(a.unpaid_domestic_hours for a in _AGENTS)
        high = counts.get("15_29", 0) + counts.get("30plus", 0)
        low = counts.get("none", 0) + counts.get("1_14", 0)
        assert high >= 100
        assert low >= 100

    def test_new_vs_established_community(self):
        """new_<1yr / recent_1_5yr vs established_5plus."""
        counts = Counter(a.community_tenure_5yr for a in _AGENTS)
        established = counts.get("established_5plus", 0)
        recent = counts.get("recent_1_5yr", 0) + counts.get("new_<1yr", 0)
        assert established >= 100
        assert recent >= 100

    def test_volunteer_subset_size(self):
        counts = Counter(a.volunteer_status for a in _AGENTS)
        assert counts.get("volunteer", 0) >= 80, (
            f"volunteer cohort {counts.get('volunteer', 0)} < 80"
        )

    def test_disability_care_subset_size(self):
        counts = Counter(a.unpaid_disability_care_hours for a in _AGENTS)
        assert counts.get("yes", 0) >= 50, (
            f"unpaid disability care cohort {counts.get('yes', 0)} < 50"
        )

    def test_non_english_only_subset(self):
        """At least 200 agents speak a language other than English at home."""
        non_english = sum(
            1 for a in _AGENTS
            if a.english_proficiency and a.english_proficiency != "english_only"
        )
        assert non_english >= 200, f"non-English cohort {non_english} < 200"

    def test_zero_car_household_subset(self):
        zero_car = sum(1 for a in _AGENTS if a.vehicles_at_dwelling == "0")
        assert zero_car >= 50, f"0-car households {zero_car} < 50"


class TestRivalHypothesisCrossings:
    """High-care vs new-arrival agents represent thesis-relevant cross-sections."""

    def test_high_care_AND_established(self):
        """Most thesis-direct cohort: high-care + long-tenure agents."""
        cohort = [
            a for a in _AGENTS
            if a.unpaid_child_care_hours in ("15_29", "30plus")
            and a.community_tenure_5yr == "established_5plus"
        ]
        assert len(cohort) >= 30, (
            f"high-care + established cohort {len(cohort)} < 30; "
            "rival hypothesis H_care_isolation can't be tested"
        )

    def test_low_care_AND_newcomer(self):
        cohort = [
            a for a in _AGENTS
            if a.unpaid_child_care_hours in ("none", "1_14")
            and a.community_tenure_5yr in ("new_<1yr", "recent_1_5yr")
        ]
        assert len(cohort) >= 30, (
            f"low-care + newcomer cohort {len(cohort)} < 30; "
            "rival hypothesis H_newcomer_lure can't be tested"
        )

    def test_volunteer_AND_established(self):
        cohort = [
            a for a in _AGENTS
            if a.volunteer_status == "volunteer"
            and a.community_tenure_5yr == "established_5plus"
        ]
        assert len(cohort) >= 30


class TestFamilyCompositionDispatchesToHousehold:
    """Verify the family_composition → household auto-mapping."""

    def test_couple_kids_under_15_maps_to_family_with_kids(self):
        for a in _AGENTS:
            if a.family_composition == "couple_kids_under_15":
                assert a.household == "family_with_kids", (
                    f"agent {a.agent_id} fc={a.family_composition} "
                    f"household={a.household}"
                )

    def test_one_parent_family_maps_to_family_with_kids(self):
        for a in _AGENTS:
            if a.family_composition == "one_parent_family":
                assert a.household == "family_with_kids"

    def test_couple_no_kids_maps_to_couple(self):
        for a in _AGENTS:
            if a.family_composition == "couple_no_kids":
                assert a.household == "couple"


class TestEnrichmentReproducibility:
    """Same seed must produce byte-equal enrichment fields."""

    def test_same_seed_same_enrichment(self):
        a = sample_population(LANE_COVE_PROFILE, seed=42)
        b = sample_population(LANE_COVE_PROFILE, seed=42)
        for x, y in zip(a, b):
            assert x.community_tenure_5yr == y.community_tenure_5yr
            assert x.unpaid_child_care_hours == y.unpaid_child_care_hours
            assert x.family_composition == y.family_composition
            assert x.volunteer_status == y.volunteer_status
            assert x.english_proficiency == y.english_proficiency

    def test_different_seed_different_enrichment(self):
        a = sample_population(LANE_COVE_PROFILE, seed=42)
        b = sample_population(LANE_COVE_PROFILE, seed=99)
        # At least one field on at least one agent should differ
        diffs = sum(
            1 for x, y in zip(a, b)
            if x.community_tenure_5yr != y.community_tenure_5yr
        )
        assert diffs > 100, f"only {diffs} differing — RNG not seed-dependent?"
