"""B1 audit: archetype coverage on 1000-agent LANE_COVE_PROFILE sample."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def coverage_audit():
    from synthetic_socio_wind_tunnel.agent.population import (
        LANE_COVE_PROFILE,
        sample_population,
    )
    from synthetic_socio_wind_tunnel.data_loader import (
        load_archetypes,
        match_archetype,
    )

    arches = load_archetypes()
    profile = LANE_COVE_PROFILE.model_copy(
        update={"name": "audit", "size": 1000},
    )
    agents = sample_population(profile, seed=42, generate_identity=False)

    matched_ids: dict[str, int] = {}
    unmatched_count = 0
    unmatched_underage = 0
    for a in agents:
        arch = match_archetype(a, arches)
        if arch is None:
            unmatched_count += 1
            if a.age < 18:
                unmatched_underage += 1
        else:
            matched_ids[arch.archetype_id] = matched_ids.get(
                arch.archetype_id, 0,
            ) + 1

    return {
        "n_total": len(agents),
        "n_matched": len(agents) - unmatched_count,
        "n_unmatched": unmatched_count,
        "n_unmatched_underage": unmatched_underage,
        "matched_ids": matched_ids,
        "n_archetypes": len(arches),
    }


class TestCoverage:

    def test_at_least_11_archetypes_loaded(self, coverage_audit):
        """B1 expansion: 7 → 11+ archetypes (added 4 fallback + 1 catch-all)."""
        assert coverage_audit["n_archetypes"] >= 11

    def test_overall_match_rate_at_least_75pct(self, coverage_audit):
        """≥ 75% of agents SHALL match an archetype."""
        rate = coverage_audit["n_matched"] / coverage_audit["n_total"]
        assert rate >= 0.75, \
            f"match rate {rate*100:.1f}% < 75% target"

    def test_adult_match_rate_100pct(self, coverage_audit):
        """≥ 18 yr olds SHALL all match (the catch-all everyday_adult covers any
        adult that doesn't fit specific archetypes).

        Unmatched should only be under-18 (kids/teens that the LANE_COVE_PROFILE
        sampling includes; outside adult archetype scope).
        """
        # Only allow under-18 to remain unmatched
        adult_unmatched = (
            coverage_audit["n_unmatched"]
            - coverage_audit["n_unmatched_underage"]
        )
        assert adult_unmatched == 0, \
            f"{adult_unmatched} adults unmatched — fallback isn't catching them"


class TestSpecificArchetypeWins:
    """Specific (non-fallback) archetypes SHALL win over catch-all when they fit."""

    def test_specific_archetypes_dominate_over_fallback(self, coverage_audit):
        """The catch-all everyday_adult should NOT account for > 50% of matches."""
        matched = coverage_audit["matched_ids"]
        n_total_matched = sum(matched.values())
        fallback_n = matched.get("everyday_adult", 0)
        # Fallback should catch a residual, not dominate
        assert fallback_n / n_total_matched < 0.5, \
            f"everyday_adult catches {fallback_n}/{n_total_matched} — too dominant"

    def test_at_least_5_specific_archetypes_used(self, coverage_audit):
        matched = coverage_audit["matched_ids"]
        non_fallback_used = sum(1 for k in matched if k != "everyday_adult")
        assert non_fallback_used >= 5
