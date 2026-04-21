"""
Phase 2 gaps audit - existence probes for Phase 2 capabilities.

Each entry here represents a Phase 2 capability declared in
`openspec/changes/phase-2-roadmap/`. These probes look for a module /
top-level API at the path where the capability will live once implemented.

Until a Phase 2 change lands, these all FAIL with mitigation pointing at
that change. This gives every Phase 2 proposal a concrete AuditResult to
cite in its `## Why` section.

When a Phase 2 change lands, the corresponding probe starts passing — the
FAIL → PASS transition is exactly the implementation signal.
"""

from __future__ import annotations

import importlib

from synthetic_socio_wind_tunnel.fitness.report import (
    AuditResult,
    AuditStatus,
    CategoryResult,
)


# Phase 2 capability → (probe path, capability description)
_PHASE2_PROBES: tuple[tuple[str, str, str, str], ...] = (
    (
        "phase2-gaps.orchestrator",
        "synthetic_socio_wind_tunnel.orchestrator",
        "Orchestrator module — tick loop, agent scheduling, path-encounter detection",
        "orchestrator",
    ),
    (
        "phase2-gaps.memory",
        "synthetic_socio_wind_tunnel.memory",
        "Memory module — 3-layer memory (event stream / daily summary / reflection)",
        "memory",
    ),
    (
        "phase2-gaps.social-graph",
        "synthetic_socio_wind_tunnel.social_graph",
        "Social graph module — agent relations + Granovetter weak-tie metric",
        "social-graph",
    ),
    (
        "phase2-gaps.model-budget",
        "synthetic_socio_wind_tunnel.model_budget",
        "Model budget module — per-tick decide_model(sonnet/haiku/skip)",
        "model-budget",
    ),
    (
        "phase2-gaps.policy-hack",
        "synthetic_socio_wind_tunnel.policy_hack",
        "Policy Hack module — unified intervention injection (5 channel types)",
        "policy-hack",
    ),
    (
        "phase2-gaps.conversation",
        "synthetic_socio_wind_tunnel.conversation",
        "Conversation module — broadcast multi-party speech + hops tracking",
        "conversation",
    ),
    (
        "phase2-gaps.metrics",
        "synthetic_socio_wind_tunnel.metrics",
        "Metrics module — 4 experiment metrics + seed-freezing for reproducibility",
        "metrics",
    ),
)


def _module_exists(dotted: str) -> bool:
    try:
        importlib.import_module(dotted)
    except ImportError:
        return False
    return True


def audit_phase2_gaps() -> CategoryResult:
    """Probe each Phase 2 capability's expected module path."""
    results: list[AuditResult] = []
    for audit_id, module_path, description, mitigation in _PHASE2_PROBES:
        present = _module_exists(module_path)
        if present:
            results.append(AuditResult(
                id=audit_id,
                status=AuditStatus.PASS,
                detail=f"{description} (found at {module_path})",
            ))
        else:
            results.append(AuditResult(
                id=audit_id,
                status=AuditStatus.FAIL,
                detail=description,
                mitigation_change=mitigation,
            ))
    return CategoryResult(category="phase2-gaps", results=tuple(results))
