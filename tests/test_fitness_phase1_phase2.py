"""Tests for phase1-baseline and phase2-gaps audits.

Key behavioural claim: after realign-to-social-thesis is applied, ALL
phase1-baseline probes except `profile-preset-ground-truthed` must PASS
(the preset intentionally stays FAIL — it's a declared placeholder);
ALL phase2-gaps probes must FAIL with mitigation_change set.
"""

from __future__ import annotations

from synthetic_socio_wind_tunnel.fitness.audits import (
    audit_phase1_baseline,
    audit_phase2_gaps,
)
from synthetic_socio_wind_tunnel.fitness.report import AuditStatus


class TestPhase1Baseline:

    def test_category_name(self):
        cat = audit_phase1_baseline()
        assert cat.category == "phase1-baseline"

    def test_attention_channel_exists(self):
        cat = audit_phase1_baseline()
        ids = {r.id for r in cat.results}
        required = {
            "phase1-baseline.attention-module",
            "phase1-baseline.attention-service",
            "phase1-baseline.feed-item-model",
            "phase1-baseline.notification-event-type",
            "phase1-baseline.observer-digital-state",
            "phase1-baseline.sense-digital",
        }
        assert required.issubset(ids)
        for r in cat.results:
            if r.id in required:
                assert r.status == AuditStatus.PASS, (r.id, r.detail)

    def test_agent_structural_fields_present(self):
        cat = audit_phase1_baseline()
        required = {
            "phase1-baseline.profile-ethnicity-group",
            "phase1-baseline.profile-housing-tenure",
            "phase1-baseline.profile-income-tier",
            "phase1-baseline.profile-work-mode",
            "phase1-baseline.profile-digital-field",
            "phase1-baseline.population-sampler",
        }
        ids_pass = {r.id for r in cat.results if r.status == AuditStatus.PASS}
        assert required.issubset(ids_pass)

    def test_ground_truth_probe_stays_fail(self):
        """The ABS-ground-truthed preset is a real Phase 2 gap we keep visible."""
        cat = audit_phase1_baseline()
        probe = next(
            r for r in cat.results
            if r.id == "phase1-baseline.profile-preset-ground-truthed"
        )
        assert probe.status == AuditStatus.FAIL
        assert probe.mitigation_change == "agent"

    def test_digital_filter_present(self):
        cat = audit_phase1_baseline()
        r = next(
            x for x in cat.results
            if x.id == "phase1-baseline.digital-attention-filter"
        )
        assert r.status == AuditStatus.PASS

    def test_fitness_audit_self_probe_passes(self):
        """The fitness module probe passes once this audit itself can run."""
        cat = audit_phase1_baseline()
        r = next(x for x in cat.results if x.id == "phase1-baseline.fitness-audit")
        assert r.status == AuditStatus.PASS


class TestPhase2Gaps:
    """
    Phase 2 gaps probes auto-flip PASS as each capability is implemented.
    Post-`orchestrator` change: `orchestrator` is now a PASS. The remaining
    unimplemented Phase 2 capabilities are still FAIL.
    """

    def test_category_name(self):
        cat = audit_phase2_gaps()
        assert cat.category == "phase2-gaps"

    def test_seven_probes_total(self):
        cat = audit_phase2_gaps()
        # 7 roadmap capabilities + multi-day-run (multi-day-simulation) = 8
        assert len(cat.results) == 8

    def test_unimplemented_capabilities_still_fail(self):
        """Capabilities still in roadmap (not yet implemented) must remain FAIL."""
        cat = audit_phase2_gaps()
        by_id = {r.id.rsplit(".", 1)[-1]: r for r in cat.results}
        # As of memory change archive, memory is implemented → PASS
        still_unimplemented = {
            "social-graph", "model-budget",
            "conversation",
        }
        for cap in still_unimplemented:
            result = by_id[cap]
            assert result.status == AuditStatus.FAIL
            assert result.mitigation_change == cap

    def test_orchestrator_now_passes(self):
        """Post-orchestrator change: phase2-gaps.orchestrator should PASS."""
        cat = audit_phase2_gaps()
        orch_result = next(r for r in cat.results if r.mitigation_change == "orchestrator"
                           or "orchestrator" in r.id)
        # After orchestrator module lands, probe auto-flips to PASS
        assert orch_result.status == AuditStatus.PASS

    def test_mitigation_covers_each_capability(self):
        """All 7 Phase 2 capabilities are probed (PASS or FAIL)."""
        cat = audit_phase2_gaps()
        # mitigation_change is set only on FAIL; PASS has None. But IDs always mention capability.
        probed_caps = set()
        for r in cat.results:
            if r.mitigation_change:
                probed_caps.add(r.mitigation_change)
            else:
                # Pass → extract from id like "phase2-gaps.orchestrator"
                cap = r.id.rsplit(".", 1)[-1]
                probed_caps.add(cap)
        expected = {
            "orchestrator",
            "multi-day-run",
            "memory",
            "social-graph",
            "model-budget",
            "policy-hack",
            "conversation",
            "metrics",
        }
        assert probed_caps == expected


class TestAnchorCoverage:
    """Verify every *unimplemented* Phase 2 change has a fail AuditResult to cite."""

    def test_every_unimplemented_phase2_change_has_fail_anchor(self):
        from synthetic_socio_wind_tunnel.fitness.audits import (
            audit_phase1_baseline,
            audit_phase2_gaps,
        )
        p1 = audit_phase1_baseline()
        p2 = audit_phase2_gaps()
        all_results = list(p1.results) + list(p2.results)

        fail_mitigations = {
            r.mitigation_change
            for r in all_results
            if r.status == AuditStatus.FAIL and r.mitigation_change
        }
        # Capabilities still waiting for implementation (post-policy-hack archive)
        unimplemented = {
            "social-graph", "model-budget",
            "conversation",
        }
        missing = unimplemented - fail_mitigations
        assert not missing, f"no fail-anchor for unimplemented caps: {missing}"
