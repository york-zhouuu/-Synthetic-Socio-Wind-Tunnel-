"""Tests for attention-induced noticing gate (thesis core mechanism)."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.attention.noticing import (
    BASE_NOTICING_RATE,
    NOTIFICATION_BASE_DELTA,
    PHONE_ATTENTION_DECAY_PER_TICK,
    baseline_screen_share,
    compute_notification_delta,
    decay_phone_attention,
    noticed_pair,
    noticing_prob,
)


class TestBaselineScreenShare:
    def test_heavy_screen_user(self):
        from synthetic_socio_wind_tunnel.attention.models import DigitalProfile
        d = DigitalProfile(daily_screen_hours=8.0)
        assert baseline_screen_share(d) == pytest.approx(0.5, abs=1e-6)

    def test_light_screen_user(self):
        from synthetic_socio_wind_tunnel.attention.models import DigitalProfile
        d = DigitalProfile(daily_screen_hours=1.0)
        assert baseline_screen_share(d) == pytest.approx(1.0 / 16.0, abs=1e-6)

    def test_clamped_to_one(self):
        from synthetic_socio_wind_tunnel.attention.models import DigitalProfile
        d = DigitalProfile(daily_screen_hours=24.0)  # impossible but defensive
        assert baseline_screen_share(d) == 1.0

    def test_none_digital(self):
        assert baseline_screen_share(None) == 0.0


class TestComputeNotificationDelta:
    def test_medium_urgency_responsive_open(self):
        delta = compute_notification_delta(
            urgency=0.5, responsiveness=0.6, openness=0.5,
        )
        # 0.10 × 0.5 × (1 + 0.2) × 1.0 = 0.06
        assert delta == pytest.approx(0.06, abs=1e-6)

    def test_zero_urgency_yields_zero_delta(self):
        delta = compute_notification_delta(0.0, 0.5, 0.5)
        assert delta == 0.0

    def test_low_responsiveness_attenuates(self):
        high = compute_notification_delta(0.5, 1.0, 0.5)
        low = compute_notification_delta(0.5, 0.0, 0.5)
        assert high > low


class TestDecay:
    def test_decay_toward_baseline(self):
        # Start at 1.0 with baseline 0.2, decay 10 times
        attn = 1.0
        baseline = 0.2
        for _ in range(10):
            attn = decay_phone_attention(attn, baseline)
        # 1.0 × 0.85**10 ≈ 0.197; floored at baseline 0.2
        assert attn == pytest.approx(0.2, abs=0.01)

    def test_decay_floor_at_baseline(self):
        attn = decay_phone_attention(0.21, baseline=0.2)
        # 0.21 × 0.85 = 0.1785 < 0.2 → clamped
        assert attn == 0.2

    def test_decay_above_baseline(self):
        attn = decay_phone_attention(1.0, baseline=0.0)
        assert attn == pytest.approx(0.85, abs=1e-6)


class TestNoticingProb:
    def test_both_free_yields_base_rate(self):
        # max(0.05, 0.05) = 0.05, free_share = 0.95, prob = 0.285
        p = noticing_prob(0.05, 0.05)
        assert p == pytest.approx(0.95 * BASE_NOTICING_RATE, abs=1e-6)

    def test_one_glued_blocks_noticing(self):
        p = noticing_prob(0.1, 0.95)
        assert p == pytest.approx(0.05 * BASE_NOTICING_RATE, abs=1e-6)

    def test_both_glued_near_zero(self):
        p = noticing_prob(0.9, 0.95)
        assert p < 0.05

    def test_clamps_above_one(self):
        # attention can be > 1 transiently
        p = noticing_prob(1.3, 0.0)
        assert p == 0.0


class TestNoticedPair:
    def test_deterministic(self):
        kw = dict(seed=42, day=0, tick=5, pair=("a", "b"))
        first = noticed_pair(0.05, 0.05, **kw)
        second = noticed_pair(0.05, 0.05, **kw)
        assert first == second

    def test_high_attention_rarely_notices(self):
        # 100 different ticks, both agents at attention 0.95 — almost no noticing
        successes = sum(
            noticed_pair(0.95, 0.95, seed=42, day=0, tick=t, pair=("a", "b"))
            for t in range(100)
        )
        assert successes < 5, f"expected <5 noticings, got {successes}"

    def test_low_attention_frequently_notices(self):
        # 100 different ticks, both agents at attention 0.0 — ~30% noticing
        successes = sum(
            noticed_pair(0.0, 0.0, seed=42, day=0, tick=t, pair=("a", "b"))
            for t in range(1000)
        )
        # base rate 0.3 ± 5% on 1000 trials
        assert 250 < successes < 350, f"expected ~300, got {successes}"


class TestB3EnvOverride:
    """fix-remaining-mechanics: SSWT_BASE_NOTICING_RATE overrides default 0.3."""

    def test_env_var_overrides_default(self, monkeypatch):
        monkeypatch.setenv("SSWT_BASE_NOTICING_RATE", "0.5")
        import importlib
        import synthetic_socio_wind_tunnel.attention.noticing as N
        importlib.reload(N)
        try:
            assert N.BASE_NOTICING_RATE == pytest.approx(0.5)
            assert N.noticing_prob(0.0, 0.0) == pytest.approx(0.5)
        finally:
            monkeypatch.delenv("SSWT_BASE_NOTICING_RATE")
            importlib.reload(N)

    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("SSWT_BASE_NOTICING_RATE", raising=False)
        import importlib
        import synthetic_socio_wind_tunnel.attention.noticing as N
        importlib.reload(N)
        assert N.BASE_NOTICING_RATE == pytest.approx(0.3)
