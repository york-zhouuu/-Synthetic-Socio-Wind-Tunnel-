"""Tests for Lane Cove social priors — pre-built day-0 ties from rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile
from synthetic_socio_wind_tunnel.agent.population import (
    LANE_COVE_PROFILE,
    sample_population,
)
from synthetic_socio_wind_tunnel.data_loader import (
    PriorTieRecord,
    SocialPriorRule,
    compute_social_priors_for_population,
    load_archetypes,
    load_social_prior_rules,
)
from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


def _profile(agent_id: str, **overrides) -> AgentProfile:
    base = dict(
        agent_id=agent_id, name=agent_id, age=35,
        occupation="banker", household="couple",
        home_location=f"home_{agent_id}",
    )
    base.update(overrides)
    return AgentProfile(**base)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


class TestLoad:

    def test_default_rules_load(self):
        rules = load_social_prior_rules()
        assert len(rules) >= 5
        ids = {r.rule_id for r in rules}
        assert "household_kin" in ids
        assert "ethnicity_enclave" in ids
        assert "archetype_peer" in ids

    def test_explicit_path(self, tmp_path: Path):
        payload = {
            "rules": [
                {
                    "rule_id": "test_a", "basis_label": "T",
                    "match": {"type": "same_home_location"},
                    "encounter_count_seed": 5, "pair_cap_per_agent": 2,
                }
            ]
        }
        p = tmp_path / "rules.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        rules = load_social_prior_rules(p)
        assert len(rules) == 1


# ---------------------------------------------------------------------------
# compute_social_priors_for_population
# ---------------------------------------------------------------------------


class TestComputeRules:

    def test_household_kin_rule(self):
        # 3 agents with same home_location → 3 pairs from "household_kin"
        rule = SocialPriorRule(
            rule_id="hk", basis_label="kin",
            match={"type": "same_home_location", "exclude_self": True},
            encounter_count_seed=60, pair_cap_per_agent=4,
        )
        profiles = [
            _profile("a", home_location="apt_x"),
            _profile("b", home_location="apt_x"),
            _profile("c", home_location="apt_x"),
            _profile("d", home_location="apt_y"),
        ]
        priors = compute_social_priors_for_population(
            profiles, rules=[rule], seed=42,
        )
        # 3 pairs (a,b),(a,c),(b,c)
        pairs = {(p.agent_a, p.agent_b) for p in priors}
        assert ("a", "b") in pairs
        assert ("a", "c") in pairs
        assert ("b", "c") in pairs
        assert all(p.encounter_count == 60 for p in priors)

    def test_same_field_rule_excludes_values(self):
        rule = SocialPriorRule(
            rule_id="enclave", basis_label="enc",
            match={
                "type": "same_field_with_constraint",
                "field": "ethnicity_group",
                "exclude_values": ["Australia"],
            },
            encounter_count_seed=4, pair_cap_per_agent=3,
        )
        profiles = [
            _profile("a", ethnicity_group="China"),
            _profile("b", ethnicity_group="China"),
            _profile("c", ethnicity_group="Australia"),
            _profile("d", ethnicity_group="Australia"),
        ]
        priors = compute_social_priors_for_population(
            profiles, rules=[rule], seed=42,
        )
        # Only (a,b) — not (c,d) since Australia is excluded
        assert len(priors) == 1
        assert priors[0].agent_a == "a" and priors[0].agent_b == "b"

    def test_pair_cap_enforced(self):
        rule = SocialPriorRule(
            rule_id="cap", basis_label="c",
            match={"type": "same_home_location"},
            encounter_count_seed=5, pair_cap_per_agent=2,
        )
        # 5 agents same home → max 2 pairs per agent (cap enforced)
        profiles = [_profile(f"a{i}", home_location="apt") for i in range(5)]
        priors = compute_social_priors_for_population(
            profiles, rules=[rule], seed=42,
        )
        # Each agent shows up in <= 2 pairs
        agent_counts: dict[str, int] = {}
        for p in priors:
            agent_counts[p.agent_a] = agent_counts.get(p.agent_a, 0) + 1
            agent_counts[p.agent_b] = agent_counts.get(p.agent_b, 0) + 1
        for a, n in agent_counts.items():
            assert n <= 2, f"agent {a} has {n} ties, cap is 2"

    def test_age_window_archetype_rule(self):
        from synthetic_socio_wind_tunnel.data_loader import ArchetypeRecord
        rule = SocialPriorRule(
            rule_id="aw", basis_label="age",
            match={"type": "same_archetype_with_age_window", "age_window": 5},
            encounter_count_seed=3, pair_cap_per_agent=4,
        )
        # All match same archetype; check age window
        archs = [ArchetypeRecord(
            archetype_id="X", label="X", approx_pct=1.0,
            match_criteria={"age_bracket_min": 18, "age_bracket_max": 80,
                            "housing_tenure": "owner_occupier",
                            "work_mode": "commute"},
            personality_bias={}, digital_bias={},
            occupation_pool=(), interests_pool=(),
            identity_text_template="", plan_text_template_examples=(),
            source_urls=(),
        )]
        profiles = [
            _profile("a", age=30, housing_tenure="owner_occupier", work_mode="commute"),
            _profile("b", age=33, housing_tenure="owner_occupier", work_mode="commute"),
            _profile("c", age=50, housing_tenure="owner_occupier", work_mode="commute"),
        ]
        priors = compute_social_priors_for_population(
            profiles, rules=[rule], archetypes=archs, seed=42,
        )
        pairs = {(p.agent_a, p.agent_b) for p in priors}
        # (a,b) age diff 3 ≤ 5 ✓; (a,c) diff 20 ✗; (b,c) diff 17 ✗
        assert ("a", "b") in pairs
        assert ("a", "c") not in pairs
        assert ("b", "c") not in pairs


# ---------------------------------------------------------------------------
# SocialGraphService.preload_ties
# ---------------------------------------------------------------------------


class TestPreloadTies:

    def test_preload_creates_ties(self):
        sg = SocialGraphService()
        priors = [
            PriorTieRecord("a", "b", 10, "rule1", "kin"),
            PriorTieRecord("a", "c", 5, "rule2", "peer"),
        ]
        n = sg.preload_ties(priors)
        assert n == 2
        assert sg.get_tie("a", "b") is not None
        assert sg.get_tie("a", "c") is not None

    def test_strength_from_encounter_count(self):
        sg = SocialGraphService(K=10)
        priors = [PriorTieRecord("a", "b", 10, "rule1", "kin")]
        sg.preload_ties(priors)
        tie = sg.get_tie("a", "b")
        # strength = 10 / (10 + 10) = 0.5
        assert tie.strength == pytest.approx(0.5, rel=0.01)

    def test_multiple_records_same_pair_summed(self):
        sg = SocialGraphService(K=10)
        priors = [
            PriorTieRecord("a", "b", 10, "rule1", "kin"),
            PriorTieRecord("a", "b", 5, "rule2", "peer"),
        ]
        sg.preload_ties(priors)
        tie = sg.get_tie("a", "b")
        # Combined N = 15 → strength 15/25 = 0.6
        assert tie.encounter_count == 15
        assert tie.strength == pytest.approx(0.6, rel=0.01)

    def test_idempotent_second_call_no_op(self):
        sg = SocialGraphService()
        priors = [PriorTieRecord("a", "b", 10, "rule1", "kin")]
        sg.preload_ties(priors)
        n2 = sg.preload_ties(priors)
        assert n2 == 0  # no new ties created
        assert sg.get_tie("a", "b").encounter_count == 10

    def test_preload_then_record_encounter(self):
        """After preload, normal record_encounter should add to count."""
        sg = SocialGraphService(K=10)
        sg.preload_ties([PriorTieRecord("a", "b", 5, "rule", "kin")])
        sg.record_encounter("a", "b", tick=1)
        tie = sg.get_tie("a", "b")
        # 5 (preloaded) + 1 (encounter) = 6
        assert tie.encounter_count == 6


# ---------------------------------------------------------------------------
# E2E: full pipeline at LANE_COVE scale
# ---------------------------------------------------------------------------


class TestE2EFullScale:

    def test_realistic_population_priors(self):
        """100 agents → expect 100-300 ties, median 2-6 ties/agent."""
        small = LANE_COVE_PROFILE.model_copy(update={"size": 100})
        profiles = sample_population(small, seed=42, num_protagonists=5)
        rules = load_social_prior_rules()
        archs = load_archetypes()
        priors = compute_social_priors_for_population(
            profiles, rules=rules, archetypes=archs, seed=42,
        )
        sg = SocialGraphService()
        sg.preload_ties(priors)

        ties_per_agent = sorted(len(sg.ties_for(p.agent_id)) for p in profiles)
        n = len(ties_per_agent)
        median = ties_per_agent[n // 2]
        assert median >= 1, f"median ties/agent = {median} too low"
        assert median <= 12, f"median ties/agent = {median} too high"

        # Total ties reasonable
        assert 20 <= len(sg._ties) <= 500

    def test_priors_dont_break_record_encounter(self):
        """After priors, the regular encounter pipeline still works."""
        small = LANE_COVE_PROFILE.model_copy(update={"size": 50})
        profiles = sample_population(small, seed=42, num_protagonists=2)
        rules = load_social_prior_rules()
        archs = load_archetypes()
        priors = compute_social_priors_for_population(
            profiles, rules=rules, archetypes=archs, seed=42,
        )
        sg = SocialGraphService()
        sg.preload_ties(priors)

        # Pick an existing tie + record more encounters
        a = profiles[0].agent_id
        b = profiles[1].agent_id
        before = sg.get_tie(a, b)
        before_count = before.encounter_count if before else 0
        sg.record_encounter(a, b, tick=1)
        sg.record_encounter(a, b, tick=2)
        after = sg.get_tie(a, b)
        assert after.encounter_count == before_count + 2
