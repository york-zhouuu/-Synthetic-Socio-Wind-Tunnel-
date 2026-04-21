"""
Phase 1 baseline audit - existence probes for Phase 1 infrastructure gaps.

These audits test whether the baseline Phase 1 codebase can support the thesis
**as-is**. They probe for the presence of modules / APIs / fields rather than
testing integration (which the e1/e2/e3 audits do).

Rationale: the realign-to-social-thesis change adds several new modules
(attention-channel, agent.population, fitness-audit). A naive audit that
uses those modules to test "Phase 1 fitness" would pass tautologically.
These baseline probes instead check whether the Phase 1 interface surface
contains what the thesis needs, without using the new modules themselves.

Status semantics:
- PASS: the probe finds the required surface (meaning realign-to-social-thesis
  or a later change has already added it).
- FAIL: the surface is missing; `mitigation_change` points at the change
  expected to add it.

Because this file runs against the **current** codebase, every entry here is
expected to PASS after realign-to-social-thesis is applied — but rerunning
against an older tag / a pure Phase 1 checkout would surface real FAILs,
demonstrating the gaps the change resolved.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.fitness.report import (
    AuditResult,
    AuditStatus,
    CategoryResult,
)

if TYPE_CHECKING:
    pass


def _module_exists(dotted: str) -> bool:
    try:
        importlib.import_module(dotted)
    except ImportError:
        return False
    return True


def _has_symbol(dotted_module: str, symbol: str) -> bool:
    try:
        mod = importlib.import_module(dotted_module)
    except ImportError:
        return False
    return hasattr(mod, symbol)


def _agent_profile_has_field(field: str) -> bool:
    try:
        from synthetic_socio_wind_tunnel.agent.profile import AgentProfile
    except ImportError:
        return False
    return field in AgentProfile.model_fields


def _observer_context_has_field(field: str) -> bool:
    try:
        from synthetic_socio_wind_tunnel.perception.models import ObserverContext
    except ImportError:
        return False
    return field in ObserverContext.model_fields


def _sense_type_has(value: str) -> bool:
    try:
        from synthetic_socio_wind_tunnel.perception.models import SenseType
    except ImportError:
        return False
    return any(s.value == value for s in SenseType)


def _event_type_has(value: str) -> bool:
    try:
        from synthetic_socio_wind_tunnel.core.errors import EventType
    except ImportError:
        return False
    return any(e.value == value for e in EventType)


def audit_phase1_baseline() -> CategoryResult:
    """Probe existence of each surface the thesis requires."""
    probes = [
        # --- attention-channel ---
        (
            "phase1-baseline.attention-module",
            "synthetic_socio_wind_tunnel.attention module exists",
            _module_exists("synthetic_socio_wind_tunnel.attention"),
            "attention-channel",
        ),
        (
            "phase1-baseline.attention-service",
            "AttentionService is importable",
            _has_symbol("synthetic_socio_wind_tunnel.attention", "AttentionService"),
            "attention-channel",
        ),
        (
            "phase1-baseline.feed-item-model",
            "FeedItem model is importable",
            _has_symbol("synthetic_socio_wind_tunnel.attention", "FeedItem"),
            "attention-channel",
        ),
        (
            "phase1-baseline.notification-event-type",
            "EventType.NOTIFICATION_RECEIVED exists (digital channel event)",
            _event_type_has("notification_received"),
            "attention-channel",
        ),
        (
            "phase1-baseline.observer-digital-state",
            "ObserverContext.digital_state field exists",
            _observer_context_has_field("digital_state"),
            "attention-channel",
        ),
        (
            "phase1-baseline.sense-digital",
            "SenseType.DIGITAL exists",
            _sense_type_has("digital"),
            "attention-channel",
        ),

        # --- agent structural dims ---
        (
            "phase1-baseline.profile-ethnicity-group",
            "AgentProfile.ethnicity_group field exists",
            _agent_profile_has_field("ethnicity_group"),
            "agent",
        ),
        (
            "phase1-baseline.profile-housing-tenure",
            "AgentProfile.housing_tenure field exists",
            _agent_profile_has_field("housing_tenure"),
            "agent",
        ),
        (
            "phase1-baseline.profile-income-tier",
            "AgentProfile.income_tier field exists",
            _agent_profile_has_field("income_tier"),
            "agent",
        ),
        (
            "phase1-baseline.profile-work-mode",
            "AgentProfile.work_mode field exists",
            _agent_profile_has_field("work_mode"),
            "agent",
        ),
        (
            "phase1-baseline.profile-digital-field",
            "AgentProfile.digital (DigitalProfile) field exists",
            _agent_profile_has_field("digital"),
            "agent",
        ),
        (
            "phase1-baseline.population-sampler",
            "agent.population.sample_population importable",
            _has_symbol("synthetic_socio_wind_tunnel.agent.population", "sample_population"),
            "agent",
        ),
        (
            "phase1-baseline.profile-preset-ground-truthed",
            "LANE_COVE_PROFILE distributions sourced from verified ABS/census data",
            False,  # intentional: preset is a placeholder, not ground-truthed
            "agent",
        ),

        # --- digital attention filter ---
        (
            "phase1-baseline.digital-attention-filter",
            "DigitalAttentionFilter module exists",
            _module_exists(
                "synthetic_socio_wind_tunnel.perception.filters.digital_attention"
            ),
            "attention-channel",
        ),

        # --- fitness-audit itself ---
        (
            "phase1-baseline.fitness-audit",
            "fitness module is available",
            _module_exists("synthetic_socio_wind_tunnel.fitness"),
            "fitness-audit",
        ),
    ]

    results: list[AuditResult] = []
    for audit_id, description, present, mitigation in probes:
        if present:
            results.append(AuditResult(
                id=audit_id,
                status=AuditStatus.PASS,
                detail=description,
            ))
        else:
            results.append(AuditResult(
                id=audit_id,
                status=AuditStatus.FAIL,
                detail=description,
                mitigation_change=mitigation,
            ))
    return CategoryResult(category="phase1-baseline", results=tuple(results))
