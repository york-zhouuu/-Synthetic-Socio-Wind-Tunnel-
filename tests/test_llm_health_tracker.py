"""Tests for LLMHealthTracker (capability 1.13).

Born out of D2 attempt 4 (2026-05-18) where 4 workers ran 16+ hours in
silent 100% fallback mode. The tracker aggregates per-call outcomes and
raises FallbackBudgetExceeded after N consecutive ticks over budget.
"""
from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.run_resilience import (
    FallbackBudgetExceeded,
    LLMHealthTracker,
    get_tracker,
    reset_tracker_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_tracker():
    """Each test starts with a fresh module-level tracker."""
    reset_tracker_for_tests()
    yield
    reset_tracker_for_tests()


class TestRollingRate:

    def test_empty_returns_zero(self):
        t = LLMHealthTracker(window_secs=10.0)
        rate, n = t.rolling_rate()
        assert rate == 0.0
        assert n == 0

    def test_all_success(self):
        t = LLMHealthTracker(window_secs=60.0)
        for _ in range(20):
            t.record_success()
        rate, n = t.rolling_rate()
        assert rate == 0.0
        assert n == 20

    def test_all_fallback(self):
        t = LLMHealthTracker(window_secs=60.0)
        for _ in range(20):
            t.record_fallback()
        rate, n = t.rolling_rate()
        assert rate == 1.0
        assert n == 20

    def test_mixed_rate(self):
        t = LLMHealthTracker(window_secs=60.0)
        for _ in range(6):
            t.record_success()
        for _ in range(4):
            t.record_fallback()
        rate, n = t.rolling_rate()
        assert rate == 0.4
        assert n == 10

    def test_all_keys_open_counts_as_fallback(self):
        t = LLMHealthTracker(window_secs=60.0)
        t.record_success()
        t.record_all_keys_open()
        rate, n = t.rolling_rate()
        assert rate == 0.5
        assert n == 2
        assert t.all_keys_open_count() == 1


class TestBudgetCheck:

    def test_below_budget_does_not_raise(self):
        t = LLMHealthTracker(
            window_secs=60.0, max_fallback_rate=0.20, ticks_to_breach=3,
        )
        for _ in range(50):
            t.record_success()
        for _ in range(5):
            t.record_fallback()
        t.check_budget()  # 5/55 = 9.1% < 20%

    def test_one_breached_tick_does_not_raise(self):
        t = LLMHealthTracker(
            window_secs=60.0, max_fallback_rate=0.20, ticks_to_breach=3,
        )
        for _ in range(40):
            t.record_fallback()
        for _ in range(10):
            t.record_success()
        # 80% rate, but only ONE tick = below ticks_to_breach
        t.check_budget()

    def test_consecutive_breach_trips(self):
        t = LLMHealthTracker(
            window_secs=60.0, max_fallback_rate=0.20, ticks_to_breach=3,
        )
        for _ in range(40):
            t.record_fallback()
        for _ in range(10):
            t.record_success()
        # 3 consecutive over-budget ticks
        t.check_budget()
        t.check_budget()
        with pytest.raises(FallbackBudgetExceeded) as ei:
            t.check_budget()
        assert ei.value.observed_rate > 0.20
        assert ei.value.ticks_breached >= 3

    def test_healthy_tick_resets_counter(self):
        t = LLMHealthTracker(
            window_secs=60.0, max_fallback_rate=0.20, ticks_to_breach=3,
        )
        for _ in range(40):
            t.record_fallback()
        for _ in range(10):
            t.record_success()
        t.check_budget()  # breach 1
        t.check_budget()  # breach 2
        # Now flush with successes — rolling rate drops below 20%
        for _ in range(300):
            t.record_success()
        t.check_budget()  # should reset counter
        # Now even if rate breaches again it takes 3 more
        for _ in range(2000):
            t.record_fallback()
        t.check_budget()  # breach 1 (re-armed)
        t.check_budget()  # breach 2
        with pytest.raises(FallbackBudgetExceeded):
            t.check_budget()  # breach 3 — trips

    def test_min_samples_guard_prevents_early_trip(self):
        """A tiny sample (e.g., 5 calls all fallback) should NOT trip the
        budget early — the rolling-window denominator needs to be big
        enough to be statistically meaningful."""
        t = LLMHealthTracker(
            window_secs=60.0, max_fallback_rate=0.20, ticks_to_breach=1,
        )
        for _ in range(5):
            t.record_fallback()
        # Default min_samples=50 → should not raise
        t.check_budget()
        t.check_budget()
        t.check_budget()


class TestProcessSingleton:

    def test_get_tracker_returns_same_instance(self):
        a = get_tracker()
        b = get_tracker()
        assert a is b

    def test_reset_creates_fresh_instance(self):
        a = get_tracker()
        a.record_fallback()
        reset_tracker_for_tests()
        b = get_tracker()
        assert a is not b
        rate, n = b.rolling_rate()
        assert rate == 0.0 and n == 0


class TestFromEnv:

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("FALLBACK_BUDGET_WINDOW_SECS", raising=False)
        monkeypatch.delenv("FALLBACK_BUDGET_MAX_RATE", raising=False)
        monkeypatch.delenv("FALLBACK_BUDGET_TICKS", raising=False)
        t = LLMHealthTracker.from_env()
        assert t.window_secs == 300.0
        assert t.max_fallback_rate == 0.20
        assert t.ticks_to_breach == 12

    def test_overrides(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FALLBACK_BUDGET_WINDOW_SECS", "60.0")
        monkeypatch.setenv("FALLBACK_BUDGET_MAX_RATE", "0.05")
        monkeypatch.setenv("FALLBACK_BUDGET_TICKS", "5")
        t = LLMHealthTracker.from_env()
        assert t.window_secs == 60.0
        assert t.max_fallback_rate == 0.05
        assert t.ticks_to_breach == 5

    def test_invalid_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FALLBACK_BUDGET_MAX_RATE", "garbage")
        t = LLMHealthTracker.from_env()
        assert t.max_fallback_rate == 0.20  # default
