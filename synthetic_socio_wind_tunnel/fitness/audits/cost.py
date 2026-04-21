"""
Cost baseline - token estimate × fixed price constants (no real LLM calls).

IMPORTANT: every constant below is an **unverified estimate**. No measurement
of actual token usage has been done in this change — Phase 1 doesn't invoke
LLMs. Numbers are order-of-magnitude sanity checks, not budgets.

Verify / replace before any Phase 2 change commits to a cost gate:
- Token counts: run a single real plan call with real prompt + measure.
- Pricing: pull from current Anthropic pricing page (these reflect ~2026-04).
- Replan rate: depends on conversation + policy-hack activity, which don't
  exist yet.
"""

from __future__ import annotations

from synthetic_socio_wind_tunnel.fitness.report import (
    AuditResult,
    AuditStatus,
    CategoryResult,
    CostBaseline,
)


# TODO(post-phase-2): replace with verified Anthropic pricing at measurement time.
_SONNET_INPUT_PER_M = 3.0     # estimated USD/M tokens, ~2026-04
_SONNET_OUTPUT_PER_M = 15.0
_HAIKU_INPUT_PER_M = 0.80
_HAIKU_OUTPUT_PER_M = 4.00

# TODO(post-phase-2): replace with measured averages from a real Planner run.
# These were picked to match roughly "~1 page of prompt, half-page of output".
_PLAN_INPUT_TOKENS = 1500
_PLAN_OUTPUT_TOKENS = 800

_REPLAN_INPUT_TOKENS = 2000
_REPLAN_OUTPUT_TOKENS = 400

_REFLECTION_INPUT_TOKENS = 2500
_REFLECTION_OUTPUT_TOKENS = 600


def _price(tokens_in: int, tokens_out: int, in_per_m: float, out_per_m: float) -> float:
    return (tokens_in * in_per_m + tokens_out * out_per_m) / 1_000_000.0


def audit_cost_baseline(
    *,
    total_agents: int = 1000,
    protagonists: int = 10,
    replans_per_agent_per_day: tuple[int, int] = (1, 8),  # (lower, upper)
    reflections_per_agent_per_day: int = 1,
) -> tuple[CategoryResult, CostBaseline]:
    """
    Estimate daily LLM cost under the 1000-agent Phase 2 scenario:

    - 1 plan/agent/day (haiku for non-protagonists, sonnet for protagonists)
    - replans: 1..8 per agent (varies by scenario)
    - 1 reflection per agent per day (haiku)

    Returns a range [lower, upper] driven by replan count.
    """
    replans_lo, replans_hi = replans_per_agent_per_day
    nonprot = total_agents - protagonists

    sonnet_calls_lo = protagonists * (1 + replans_lo + reflections_per_agent_per_day)
    sonnet_calls_hi = protagonists * (1 + replans_hi + reflections_per_agent_per_day)

    haiku_calls_lo = nonprot * (1 + replans_lo + reflections_per_agent_per_day)
    haiku_calls_hi = nonprot * (1 + replans_hi + reflections_per_agent_per_day)

    def _sonnet_cost(calls: int) -> float:
        # average over plan / replan / reflection per call mix
        avg_in = (_PLAN_INPUT_TOKENS + _REPLAN_INPUT_TOKENS + _REFLECTION_INPUT_TOKENS) / 3
        avg_out = (_PLAN_OUTPUT_TOKENS + _REPLAN_OUTPUT_TOKENS + _REFLECTION_OUTPUT_TOKENS) / 3
        return calls * _price(int(avg_in), int(avg_out), _SONNET_INPUT_PER_M,
                              _SONNET_OUTPUT_PER_M)

    def _haiku_cost(calls: int) -> float:
        avg_in = (_PLAN_INPUT_TOKENS + _REPLAN_INPUT_TOKENS + _REFLECTION_INPUT_TOKENS) / 3
        avg_out = (_PLAN_OUTPUT_TOKENS + _REPLAN_OUTPUT_TOKENS + _REFLECTION_OUTPUT_TOKENS) / 3
        return calls * _price(int(avg_in), int(avg_out), _HAIKU_INPUT_PER_M,
                              _HAIKU_OUTPUT_PER_M)

    sonnet_lo = _sonnet_cost(sonnet_calls_lo)
    sonnet_hi = _sonnet_cost(sonnet_calls_hi)
    haiku_lo = _haiku_cost(haiku_calls_lo)
    haiku_hi = _haiku_cost(haiku_calls_hi)

    total_lo = sonnet_lo + haiku_lo
    total_hi = sonnet_hi + haiku_hi

    baseline = CostBaseline(
        sonnet_calls_estimated=(sonnet_calls_lo + sonnet_calls_hi) // 2,
        haiku_calls_estimated=(haiku_calls_lo + haiku_calls_hi) // 2,
        skip_calls_estimated=0,
        sonnet_cost_usd_lower=sonnet_lo,
        sonnet_cost_usd_upper=sonnet_hi,
        haiku_cost_usd_lower=haiku_lo,
        haiku_cost_usd_upper=haiku_hi,
        total_usd_lower=total_lo,
        total_usd_upper=total_hi,
        notes=(
            f"ESTIMATE (no real LLM calls). {total_agents} agents "
            f"({protagonists} sonnet / {nonprot} haiku), replans/day="
            f"{replans_lo}-{replans_hi}. Token & price constants in cost.py "
            "are order-of-magnitude placeholders; verify before committing "
            "to a cost gate."
        ),
    )

    # Gate: we want total daily cost < $200 (sanity upper bound for a dev run)
    if total_hi <= 200.0:
        status = AuditStatus.PASS
        detail = f"daily total range: ${total_lo:.2f} - ${total_hi:.2f}"
        mitigation = None
    else:
        status = AuditStatus.FAIL
        detail = (
            f"daily total upper bound ${total_hi:.2f} exceeds $200 safety gate; "
            "model-budget capability must tighten"
        )
        mitigation = "model-budget"

    cat = CategoryResult(
        category="cost-baseline",
        results=(AuditResult(
            id="cost.daily-upper-bound",
            status=status,
            detail=detail,
            mitigation_change=mitigation,
            extras={
                "total_usd_lower": total_lo,
                "total_usd_upper": total_hi,
                "sonnet_calls_lo": sonnet_calls_lo,
                "sonnet_calls_hi": sonnet_calls_hi,
                "haiku_calls_lo": haiku_calls_lo,
                "haiku_calls_hi": haiku_calls_hi,
            },
        ),),
    )
    return cat, baseline
