"""B3 audit: social_priors actually produce ties on 1000-agent population."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def audit_priors():
    from synthetic_socio_wind_tunnel.agent.population import (
        LANE_COVE_PROFILE,
        sample_population,
    )
    from synthetic_socio_wind_tunnel.data_loader import (
        compute_social_priors_for_population,
        load_archetypes,
        load_social_prior_rules,
    )

    archetypes = load_archetypes()
    rules = load_social_prior_rules()
    profile = LANE_COVE_PROFILE.model_copy(
        update={"name": "audit", "size": 1000},
    )
    agents = sample_population(profile, seed=42, generate_identity=False)
    priors = compute_social_priors_for_population(
        agents, rules=rules, archetypes=archetypes, seed=42,
    )

    rule_ties: dict[str, int] = {}
    pair_seen: set = set()
    for rec in priors:
        rule_ties[rec.rule_id] = rule_ties.get(rec.rule_id, 0) + 1
        pair_seen.add(tuple(sorted([rec.agent_a, rec.agent_b])))

    return {
        "rules": rules,
        "rule_ties": rule_ties,
        "distinct_pairs": len(pair_seen),
        "total_records": len(priors),
    }


class TestRulesProduceTies:

    def test_total_pairs_in_reasonable_range(self, audit_priors):
        n = audit_priors["distinct_pairs"]
        assert 100 < n < 100_000, \
            f"distinct pairs {n} out of expected range [100, 100K]"

    def test_all_6_rules_fire(self, audit_priors):
        """B3 + A2: all 6 rules SHALL fire ≥ 1 tie post household-clustering.

        Pre-A2: household_kin fired 0 because sample_population gave each agent
        unique home_location. A2 (realism-household-coupling) clusters agents
        by family_composition → shared home_location → household_kin fires.
        """
        rule_ties = audit_priors["rule_ties"]
        fired = sum(1 for r, n in rule_ties.items() if n > 0)
        assert fired == 6, f"expected all 6 rules to fire, only {fired} did"


class TestHouseholdKinFiresPostA2:

    def test_household_kin_fires_after_clustering(self, audit_priors):
        """A2 / realism-household-coupling: household_kin SHALL produce ties
        because agents are now clustered into shared home_location."""
        rule_ties = audit_priors["rule_ties"]
        n = rule_ties.get("household_kin", 0)
        assert n >= 100, f"household_kin only fired {n} ties post A2 clustering"


class TestExpectedHighProducers:

    def test_archetype_peer_fires_many(self, audit_priors):
        """archetype_peer should produce a substantial number of ties."""
        n = audit_priors["rule_ties"].get("archetype_peer", 0)
        assert n >= 50, f"archetype_peer only fired {n} ties"

    def test_school_parent_peer_fires(self, audit_priors):
        n = audit_priors["rule_ties"].get("school_parent_peer", 0)
        assert n >= 10, f"school_parent_peer only fired {n} ties"
