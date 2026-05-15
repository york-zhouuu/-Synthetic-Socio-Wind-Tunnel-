"""Integration tests for tier_llm_factory + run_resilience wiring.

Verifies:
- All 3 real-provider tier clients inject httpx with keepalive=0
- Multi-key resolution: GEMINI_API_KEYS / DEEPSEEK_API_KEYS
- Single-key fallback: GEMINI_API_KEY / DEEPSEEK_API_KEY
- Shared RetryPolicy instance across tiers
- RESILIENCE_DISABLE=1 skips hardening (legacy path)
- Per-key PerKeyCircuitBreaker prevents calls when open
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure fake env keys exist for construction
import os
os.environ.setdefault("GEMINI_API_KEY", "dummy-gemini")
os.environ.setdefault("DEEPSEEK_API_KEY", "dummy-deepseek")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-dummy-anthropic")

from synthetic_socio_wind_tunnel.run_resilience import (
    AllKeysOpenError,
    PerKeyCircuitBreaker,
    RetryPolicy,
)
from tools.tier_llm_factory import (
    HttpxPoolConfig,
    _AnthropicTierClient,
    _DeepSeekTierClient,
    _GeminiTierClient,
    _LegacyAnthropicTierClient,
    build_tier_clients,
)


def _pool_of(httpx_client) -> object:
    return httpx_client._transport._pool


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

class TestGeminiKeepaliveZero:

    def test_gemini_client_has_keepalive_zero(self):
        clients = build_tier_clients(provider="gemini")
        gc = clients["sonnet"]
        assert isinstance(gc, _GeminiTierClient)
        ctx = gc._contexts[0]
        pool = _pool_of(ctx.httpx_client)
        assert pool._max_keepalive_connections == 0
        assert pool._max_connections == 600

    def test_gemini_multi_key_round_robin(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GEMINI_API_KEYS", "k1,k2,k3")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        clients = build_tier_clients(provider="gemini")
        gc = clients["sonnet"]
        assert len(gc._contexts) == 3
        keys = [ctx.key_value for ctx in gc._contexts]
        assert keys == ["k1", "k2", "k3"]

    def test_gemini_single_key_fallback(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "only-one")
        clients = build_tier_clients(provider="gemini")
        gc = clients["sonnet"]
        assert len(gc._contexts) == 1
        assert gc._contexts[0].key_value == "only-one"


# ---------------------------------------------------------------------------
# DeepSeek
# ---------------------------------------------------------------------------

class TestDeepSeekKeepaliveZero:

    def test_deepseek_client_has_keepalive_zero(self):
        clients = build_tier_clients(provider="deepseek")
        dc = clients["sonnet"]
        assert isinstance(dc, _DeepSeekTierClient)
        ctx = dc._contexts[0]
        pool = _pool_of(ctx.httpx_client)
        assert pool._max_keepalive_connections == 0

    def test_deepseek_multi_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DEEPSEEK_API_KEYS", "ds1,ds2")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        clients = build_tier_clients(provider="deepseek")
        dc = clients["sonnet"]
        assert len(dc._contexts) == 2


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

class TestAnthropicKeepaliveZero:

    def test_anthropic_client_has_keepalive_zero(self):
        clients = build_tier_clients(provider="anthropic")
        ac = clients["sonnet"]
        assert isinstance(ac, _AnthropicTierClient)
        pool = _pool_of(ac._ctx.httpx_client)
        assert pool._max_keepalive_connections == 0


# ---------------------------------------------------------------------------
# Shared policy
# ---------------------------------------------------------------------------

class TestSharedRetryPolicy:

    def test_retry_policy_shared_across_clients(self):
        policy = RetryPolicy(max_attempts=7, base_backoff_seconds=2.0)
        clients = build_tier_clients(provider="gemini", retry_policy=policy)
        # All 3 tier clients should share the *same* policy instance
        assert clients["sonnet"]._retry_policy is policy
        assert clients["haiku"]._retry_policy is policy
        assert clients["nano"]._retry_policy is policy

    def test_pool_config_propagates(self):
        cfg = HttpxPoolConfig(
            max_connections=200, max_keepalive_connections=0,
            connect_timeout=5.0, read_timeout=30.0,
        )
        clients = build_tier_clients(provider="gemini", pool_config=cfg)
        ctx = clients["sonnet"]._contexts[0]
        pool = _pool_of(ctx.httpx_client)
        assert pool._max_connections == 200

    def test_env_override_pool_keepalive(self, monkeypatch: pytest.MonkeyPatch):
        """RESILIENCE_POOL_MAX_KEEPALIVE=10 overrides the default 0."""
        monkeypatch.setenv("RESILIENCE_POOL_MAX_KEEPALIVE", "10")
        clients = build_tier_clients(provider="deepseek")
        ctx = clients["sonnet"]._contexts[0]
        pool = _pool_of(ctx.httpx_client)
        assert pool._max_keepalive_connections == 10


# ---------------------------------------------------------------------------
# RESILIENCE_DISABLE escape hatch
# ---------------------------------------------------------------------------

class TestResilienceDisable:

    def test_resilience_disable_skips_hardening_anthropic(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ):
        monkeypatch.setenv("RESILIENCE_DISABLE", "1")
        clients = build_tier_clients(provider="anthropic")
        # Legacy path returns _LegacyAnthropicTierClient
        assert isinstance(clients["sonnet"], _LegacyAnthropicTierClient)
        captured = capsys.readouterr()
        assert "RESILIENCE_DISABLE" in captured.err

    def test_resilience_disable_gemini_still_keepalive_zero(
        self, monkeypatch: pytest.MonkeyPatch,
    ):
        """For Gemini/DeepSeek, disable raises breaker thresholds but
        keepalive=0 remains — losing it would re-introduce the D1' root cause."""
        monkeypatch.setenv("RESILIENCE_DISABLE", "1")
        clients = build_tier_clients(provider="gemini")
        ctx = clients["sonnet"]._contexts[0]
        pool = _pool_of(ctx.httpx_client)
        assert pool._max_keepalive_connections == 0


# ---------------------------------------------------------------------------
# RetryPolicy integration in generate()
# ---------------------------------------------------------------------------

def _ds_response(text: str, prompt_tokens: int = 1, completion_tokens: int = 1):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        ),
    )


class TestRetryIntegration:

    def test_retryable_then_success(self):
        """ConnectionError on attempt 0 → backoff → success on attempt 1."""
        policy = RetryPolicy(max_attempts=3, base_backoff_seconds=0.001, jitter_ratio=0)
        c = _DeepSeekTierClient(
            tier="haiku", model="deepseek-v4-flash", max_tokens=512,
            api_keys=["k1"], retry_policy=policy,
        )

        calls = []

        async def fake(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ConnectionError("transient blip")
            return _ds_response("ok")

        mock_sdk = MagicMock()
        mock_sdk.chat.completions.create = fake
        c._contexts[0].sdk_client = mock_sdk

        result = asyncio.run(c.generate("test"))
        assert result == "ok"
        assert len(calls) == 2

    def test_fatal_immediate_raise(self):
        policy = RetryPolicy(max_attempts=5, base_backoff_seconds=0.001)
        c = _DeepSeekTierClient(
            tier="sonnet", model="deepseek-v4-pro", max_tokens=1024,
            api_keys=["k1"], retry_policy=policy,
        )

        class FakeAuthError(Exception):
            status_code = 401

        calls = []

        async def fake(**kwargs):
            calls.append(1)
            raise FakeAuthError("bad key")

        mock_sdk = MagicMock()
        mock_sdk.chat.completions.create = fake
        c._contexts[0].sdk_client = mock_sdk

        with pytest.raises(FakeAuthError):
            asyncio.run(c.generate("test"))
        assert len(calls) == 1  # no retry

    def test_retry_exhausted_raises_last(self):
        policy = RetryPolicy(max_attempts=3, base_backoff_seconds=0.001, jitter_ratio=0)
        c = _DeepSeekTierClient(
            tier="sonnet", model="deepseek-v4-pro", max_tokens=1024,
            api_keys=["k1"], retry_policy=policy,
        )

        calls = []

        async def fake(**kwargs):
            calls.append(1)
            raise ConnectionError(f"attempt {len(calls)}")

        mock_sdk = MagicMock()
        mock_sdk.chat.completions.create = fake
        c._contexts[0].sdk_client = mock_sdk

        with pytest.raises(ConnectionError):
            asyncio.run(c.generate("test"))
        assert len(calls) == 3


# ---------------------------------------------------------------------------
# Circuit breaker integration
# ---------------------------------------------------------------------------

class TestCircuitBreakerIntegration:

    def test_all_keys_open_raises(self):
        """All breakers open → AllKeysOpenError without calling SDK."""
        breaker_factory = lambda: PerKeyCircuitBreaker(  # noqa: E731
            failure_threshold=1, cooldown_seconds=10.0,
        )
        c = _DeepSeekTierClient(
            tier="haiku", model="deepseek-v4-flash", max_tokens=512,
            api_keys=["k1"], retry_policy=RetryPolicy(max_attempts=1),
            circuit_breaker_factory=breaker_factory,
        )

        async def fail_fake(**kwargs):
            raise ConnectionError("oops")

        mock_sdk = MagicMock()
        mock_sdk.chat.completions.create = fail_fake
        c._contexts[0].sdk_client = mock_sdk

        # First call: trips the breaker
        with pytest.raises(ConnectionError):
            asyncio.run(c.generate("p"))
        # Second call: breaker is open, AllKeysOpenError before SDK invoked
        with pytest.raises(AllKeysOpenError):
            asyncio.run(c.generate("p"))

    def test_multi_key_round_robin_skips_open(self):
        breakers = [
            PerKeyCircuitBreaker(failure_threshold=10),  # k1: closed
            PerKeyCircuitBreaker(failure_threshold=10),  # k2: closed
        ]
        supply = iter(breakers)

        c = _DeepSeekTierClient(
            tier="haiku", model="deepseek-v4-flash", max_tokens=512,
            api_keys=["k1", "k2"], retry_policy=RetryPolicy(max_attempts=1),
            circuit_breaker_factory=lambda: next(supply),
        )
        # Pre-open k1's breaker manually
        for _ in range(15):
            c._contexts[0].breaker.record_failure()
        assert c._contexts[0].breaker.state == "open"

        # Mock both SDKs
        calls = {"k1": 0, "k2": 0}

        def make_fake(label):
            async def fake(**kwargs):
                calls[label] += 1
                return _ds_response("ok")
            return fake

        c._contexts[0].sdk_client = MagicMock()
        c._contexts[0].sdk_client.chat.completions.create = make_fake("k1")
        c._contexts[1].sdk_client = MagicMock()
        c._contexts[1].sdk_client.chat.completions.create = make_fake("k2")

        # Calls should all hit k2
        for _ in range(3):
            asyncio.run(c.generate("p"))

        assert calls["k1"] == 0
        assert calls["k2"] == 3
