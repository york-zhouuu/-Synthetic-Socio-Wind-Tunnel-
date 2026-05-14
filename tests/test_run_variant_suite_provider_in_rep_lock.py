"""Tests for B10: rep_lock.provider must reflect actual LLM provider.

Original code in run_variant_suite.py:793 hardcoded provider=None to
compute_reproducibility_lock, so model_version was always "stub:v1"
regardless of whether the run used Gemini, Anthropic, or stub.
"""

from __future__ import annotations

from synthetic_socio_wind_tunnel.metrics.reproducibility import (
    compute_reproducibility_lock,
)


class TestProviderField:

    def test_stub_provider_explicit(self):
        lock = compute_reproducibility_lock(
            seed_pool=[42],
            use_real_llm=False,
            variant_names=["baseline"],
            phase_config={"baseline_days": 1, "intervention_days": 1, "post_days": 1},
            provider="stub",
        )
        assert lock["provider"] == "stub"
        assert lock["model_version"] == "stub:v1"

    def test_anthropic_provider(self):
        lock = compute_reproducibility_lock(
            seed_pool=[42],
            use_real_llm=True,
            variant_names=["baseline"],
            phase_config={"baseline_days": 1, "intervention_days": 1, "post_days": 1},
            provider="anthropic",
        )
        assert lock["provider"] == "anthropic"
        assert "anthropic" in lock["model_version"]
        assert lock["model_version"] != "stub:v1"

    def test_gemini_provider(self):
        lock = compute_reproducibility_lock(
            seed_pool=[42],
            use_real_llm=False,  # ai-town path: stub planner + Gemini handlers
            variant_names=["baseline"],
            phase_config={"baseline_days": 1, "intervention_days": 1, "post_days": 1},
            provider="gemini",
        )
        assert lock["provider"] == "gemini"
        assert "gemini" in lock["model_version"], \
            f"model_version SHALL reflect gemini, got: {lock['model_version']}"

    def test_provider_none_falls_back_to_use_real_llm(self):
        """Backwards compat: provider=None → derive from use_real_llm."""
        lock_stub = compute_reproducibility_lock(
            seed_pool=[42],
            use_real_llm=False,
            variant_names=["baseline"],
            phase_config={"baseline_days": 1, "intervention_days": 1, "post_days": 1},
            provider=None,
        )
        assert lock_stub["provider"] == "stub"

        lock_anthropic = compute_reproducibility_lock(
            seed_pool=[42],
            use_real_llm=True,
            variant_names=["baseline"],
            phase_config={"baseline_days": 1, "intervention_days": 1, "post_days": 1},
            provider=None,
        )
        assert lock_anthropic["provider"] == "anthropic"


class TestProviderInSuiteOutput:
    """Verify the suite-level run_seed_with_metrics actually plumbs provider through."""

    def test_default_run_records_stub_provider(self):
        """Default suite run (no --use-aitown, no --use-real-llm) records stub."""
        from datetime import date
        import sys
        from pathlib import Path

        ROOT = Path(__file__).resolve().parents[1]
        TOOLS = ROOT / "tools"
        if str(TOOLS) not in sys.path:
            sys.path.insert(0, str(TOOLS))
        from run_variant_suite import run_seed_with_metrics  # type: ignore

        _result, run_metrics, _meta = run_seed_with_metrics(
            seed=42,
            n_agents=10,
            start_date=date(2026, 4, 22),
            num_days=1,
            mode="dev",
            variant_name="baseline",
            phase_days="1,1,1",
            use_real_llm=False,
            use_aitown=False,
        )
        rep = run_metrics.extensions["reproducibility_lock"]
        assert rep["provider"] == "stub"
        assert rep["model_version"] == "stub:v1"
