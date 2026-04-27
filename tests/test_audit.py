"""Unit tests for synthetic_socio_wind_tunnel.agent.audit."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.agent import LANE_COVE_PROFILE, sample_population
from synthetic_socio_wind_tunnel.agent.audit import (
    AuditStatus,
    BehavioralDistance,
    RunSummary,
    assess_blind_acceptance,
    assess_cross_model_convergence,
    assess_swap_acceptance,
    blind_profile_attribute,
    compute_behavioral_distance,
    swap_profile_attribute,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sample_agent():
    return sample_population(LANE_COVE_PROFILE, seed=42)[0]


# ---------------------------------------------------------------------------
# swap / blind helpers
# ---------------------------------------------------------------------------

class TestSwapProfileAttribute:

    def test_swap_gender_keeps_other_fields(self, sample_agent):
        """All non-swapped fields (incl. 13 enrichment) must be byte-identical."""
        original = sample_agent
        new_gender = "male" if original.gender == "female" else "female"
        swapped = swap_profile_attribute(original, "gender", new_gender)

        assert swapped.gender == new_gender
        # Core identity
        assert swapped.agent_id == original.agent_id
        assert swapped.name == original.name
        assert swapped.age == original.age
        assert swapped.occupation == original.occupation
        assert swapped.home_location == original.home_location
        # Personality (deep object)
        assert swapped.personality.curiosity == original.personality.curiosity
        assert swapped.personality.extraversion == original.personality.extraversion
        # 13 enrichment fields
        for attr in (
            "community_tenure_5yr", "unpaid_child_care_hours",
            "unpaid_domestic_hours", "unpaid_disability_care_hours",
            "volunteer_status", "english_proficiency", "family_composition",
            "dwelling_structure", "vehicles_at_dwelling",
            "year_of_arrival_bucket", "indigenous_status",
            "disability_status", "education_level",
        ):
            assert getattr(swapped, attr) == getattr(original, attr), \
                f"swap leaked into {attr}"

    def test_swap_ethnicity_keeps_other_fields(self, sample_agent):
        original = sample_agent
        new_ethnicity = "Vietnam" if original.ethnicity_group == "Australia" else "Australia"
        swapped = swap_profile_attribute(original, "ethnicity_group", new_ethnicity)
        assert swapped.ethnicity_group == new_ethnicity
        assert swapped.gender == original.gender
        assert swapped.housing_tenure == original.housing_tenure

    def test_swap_unknown_attribute_raises(self, sample_agent):
        with pytest.raises(ValueError, match="no field"):
            swap_profile_attribute(sample_agent, "not_a_real_field", "x")

    def test_swap_returns_new_object(self, sample_agent):
        """Mutation safety: original profile must not be mutated."""
        before_gender = sample_agent.gender
        _ = swap_profile_attribute(sample_agent, "gender", "non_binary")
        assert sample_agent.gender == before_gender


class TestBlindProfileAttribute:

    def test_blind_sets_field_to_none(self, sample_agent):
        blinded = blind_profile_attribute(sample_agent, "ethnicity_group")
        assert blinded.ethnicity_group is None

    def test_blind_keeps_other_fields(self, sample_agent):
        blinded = blind_profile_attribute(sample_agent, "ethnicity_group")
        assert blinded.gender == sample_agent.gender
        assert blinded.community_tenure_5yr == sample_agent.community_tenure_5yr
        assert blinded.name == sample_agent.name

    def test_blind_unknown_attribute_raises(self, sample_agent):
        with pytest.raises(ValueError, match="no field"):
            blind_profile_attribute(sample_agent, "not_a_real_field")


# ---------------------------------------------------------------------------
# Distance computation
# ---------------------------------------------------------------------------

class TestComputeBehavioralDistance:

    def test_identical_runs_zero_distance(self):
        run = RunSummary(
            agent_destinations={"a1": "cafe", "a2": "park", "a3": "home"},
            encounter_count=42,
            move_event_count=100,
        )
        d = compute_behavioral_distance(run, run)
        assert d.destination_overlap_pct == 1.0
        assert d.encounter_count_delta_pct == 0.0
        assert d.n_agents == 3

    def test_disjoint_runs_zero_overlap(self):
        a = RunSummary(
            agent_destinations={"a1": "cafe", "a2": "park"},
            encounter_count=10, move_event_count=20,
        )
        b = RunSummary(
            agent_destinations={"a1": "library", "a2": "shop"},
            encounter_count=10, move_event_count=20,
        )
        d = compute_behavioral_distance(a, b)
        assert d.destination_overlap_pct == 0.0
        assert d.encounter_count_delta_pct == 0.0  # same enc count

    def test_half_overlap(self):
        a = RunSummary(
            agent_destinations={"a1": "cafe", "a2": "park"},
            encounter_count=10, move_event_count=20,
        )
        b = RunSummary(
            agent_destinations={"a1": "cafe", "a2": "shop"},
            encounter_count=10, move_event_count=20,
        )
        d = compute_behavioral_distance(a, b)
        assert d.destination_overlap_pct == 0.5

    def test_encounter_delta_pct(self):
        a = RunSummary(agent_destinations={"a1": "x"}, encounter_count=10)
        b = RunSummary(agent_destinations={"a1": "x"}, encounter_count=15)
        d = compute_behavioral_distance(a, b)
        # |10 - 15| / 12.5 = 0.4
        assert abs(d.encounter_count_delta_pct - 0.4) < 1e-6

    def test_no_common_agents(self):
        a = RunSummary(agent_destinations={"a1": "x"}, encounter_count=5)
        b = RunSummary(agent_destinations={"b1": "y"}, encounter_count=5)
        d = compute_behavioral_distance(a, b)
        # Vacuous identity; n_agents = 0 means caller should ignore signal
        assert d.n_agents == 0


# ---------------------------------------------------------------------------
# Acceptance checks
# ---------------------------------------------------------------------------

class TestAssessSwapAcceptance:

    def _dist(self, overlap):
        return BehavioralDistance(
            destination_overlap_pct=overlap,
            encounter_count_delta_pct=0.0,
            n_agents=100,
        )

    def test_stub_pass_at_threshold(self):
        # 1 - 0.95 = 0.05 == threshold (≤) → PASS
        assert assess_swap_acceptance(self._dist(0.95), mode="stub") == AuditStatus.PASS

    def test_stub_fail_just_above_threshold(self):
        # 1 - 0.94 = 0.06 > 0.05 → FAIL
        assert assess_swap_acceptance(self._dist(0.94), mode="stub") == AuditStatus.FAIL

    def test_real_llm_more_lenient(self):
        # 1 - 0.92 = 0.08; stub fails (>0.05), real_llm passes (<0.10)
        d = self._dist(0.92)
        assert assess_swap_acceptance(d, mode="stub") == AuditStatus.FAIL
        assert assess_swap_acceptance(d, mode="real_llm") == AuditStatus.PASS

    def test_real_llm_fail_just_above_threshold(self):
        # 1 - 0.89 = 0.11 > 0.10 → FAIL
        assert assess_swap_acceptance(self._dist(0.89), mode="real_llm") == AuditStatus.FAIL


class TestAssessBlindAcceptance:

    def _dist(self, overlap):
        return BehavioralDistance(
            destination_overlap_pct=overlap,
            encounter_count_delta_pct=0.0,
            n_agents=100,
        )

    def test_pass_at_threshold(self):
        assert assess_blind_acceptance(self._dist(0.80)) == AuditStatus.PASS

    def test_fail_just_below(self):
        assert assess_blind_acceptance(self._dist(0.79)) == AuditStatus.FAIL

    def test_pass_above_threshold(self):
        assert assess_blind_acceptance(self._dist(0.95)) == AuditStatus.PASS


class TestAssessCrossModelConvergence:

    def test_pass_when_evidence_match(self):
        report_a = {"evidence_alignment": "consistent"}
        report_b = {"evidence_alignment": "consistent"}
        assert assess_cross_model_convergence(report_a, report_b) == AuditStatus.PASS

    def test_fail_when_evidence_mismatch(self):
        report_a = {"evidence_alignment": "consistent"}
        report_b = {"evidence_alignment": "not_consistent"}
        assert assess_cross_model_convergence(report_a, report_b) == AuditStatus.FAIL

    def test_fail_when_either_missing(self):
        assert assess_cross_model_convergence({}, {"evidence_alignment": "consistent"}) == AuditStatus.FAIL
        assert assess_cross_model_convergence({"evidence_alignment": "consistent"}, {}) == AuditStatus.FAIL


# ---------------------------------------------------------------------------
# Hot-path isolation
# ---------------------------------------------------------------------------

class TestHotPathIsolation:
    """audit module SHALL NOT be imported by sim runtime / planner / orchestrator."""

    def test_runtime_does_not_import_audit(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c", (
                "import sys; "
                "import synthetic_socio_wind_tunnel.agent.runtime; "
                "import synthetic_socio_wind_tunnel.agent.planner; "
                "assert 'synthetic_socio_wind_tunnel.agent.audit' not in sys.modules, "
                "    'audit module leaked into hot path'"
            )],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr

    def test_orchestrator_does_not_import_audit(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c", (
                "import sys; "
                "import synthetic_socio_wind_tunnel.orchestrator; "
                "assert 'synthetic_socio_wind_tunnel.agent.audit' not in sys.modules"
            )],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
