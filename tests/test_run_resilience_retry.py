"""Tests for synthetic_socio_wind_tunnel.run_resilience.retry."""

from __future__ import annotations

import asyncio

import pytest

from synthetic_socio_wind_tunnel.run_resilience.retry import RetryPolicy


def test_retry_policy_defaults() -> None:
    p = RetryPolicy()
    assert p.max_attempts == 3
    assert p.base_backoff_seconds == 0.5
    assert p.max_backoff_seconds == 8.0
    assert p.jitter_ratio == 0.2
    # spec 要求：retryable HTTP statuses 至少含 429 / 500 / 502 / 503 / 504
    assert {429, 500, 502, 503, 504}.issubset(set(p.retryable_http_statuses))
    # fatal HTTP statuses 至少含 400 / 401 / 403 / 404
    assert {400, 401, 403, 404}.issubset(set(p.fatal_http_statuses))


def test_next_backoff_exponential_with_jitter() -> None:
    # 锁定 random seed 让 jitter 可预测
    import random as _random
    _random.seed(0)
    p = RetryPolicy(base_backoff_seconds=0.5, max_backoff_seconds=8.0, jitter_ratio=0.2)

    b0 = p.next_backoff(0)  # base = 0.5 → range [0.4, 0.6]
    assert 0.4 <= b0 <= 0.6

    b1 = p.next_backoff(1)  # base = 1.0 → range [0.8, 1.2]
    assert 0.8 <= b1 <= 1.2

    # attempt 5: base = 0.5 * 2^5 = 16 → capped at 8 → range [6.4, 9.6]
    # 上限 capped at 8.0；jitter 仍可超 → 但 capped 在 capped 后才 jitter
    # 实现：base = min(0.5 * 2^5, max_backoff) = min(16, 8) = 8 → jitter ±20% → [6.4, 9.6]
    b5 = p.next_backoff(5)
    assert 6.4 <= b5 <= 9.6


def test_next_backoff_no_jitter_returns_capped() -> None:
    p = RetryPolicy(base_backoff_seconds=0.5, max_backoff_seconds=8.0, jitter_ratio=0.0)
    assert p.next_backoff(5) == pytest.approx(8.0)


def test_classify_connection_error_retryable() -> None:
    p = RetryPolicy()
    assert p.classify(ConnectionError("boom")) == "retryable"


def test_classify_timeout_error_retryable() -> None:
    p = RetryPolicy()
    assert p.classify(TimeoutError("slow")) == "retryable"
    assert p.classify(asyncio.TimeoutError()) == "retryable"


def test_classify_401_fatal() -> None:
    p = RetryPolicy()

    class FakeAPIStatusError(Exception):
        def __init__(self) -> None:
            super().__init__("unauthorized")
            self.status_code = 401

    assert p.classify(FakeAPIStatusError()) == "fatal"


def test_classify_429_retryable() -> None:
    p = RetryPolicy()

    class FakeRateLimit(Exception):
        status_code = 429

    assert p.classify(FakeRateLimit()) == "retryable"


def test_classify_500_retryable() -> None:
    p = RetryPolicy()

    class FakeServerError(Exception):
        status_code = 500

    assert p.classify(FakeServerError()) == "retryable"


def test_classify_400_fatal() -> None:
    p = RetryPolicy()

    class FakeBadRequest(Exception):
        status_code = 400

    assert p.classify(FakeBadRequest()) == "fatal"


def test_classify_genai_style_code() -> None:
    """google-genai ServerError 用 .code 字段而非 .status_code。"""
    p = RetryPolicy()

    class FakeGenaiError(Exception):
        code = 503

    assert p.classify(FakeGenaiError()) == "retryable"


def test_classify_httpx_style_response() -> None:
    p = RetryPolicy()

    class FakeResponse:
        status_code = 502

    class FakeHttpxStatusError(Exception):
        response = FakeResponse()

    assert p.classify(FakeHttpxStatusError()) == "retryable"


def test_classify_unknown_value_error() -> None:
    p = RetryPolicy()
    assert p.classify(ValueError("nope")) == "unknown"


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "RESILIENCE_RETRY_MAX_ATTEMPTS",
        "RESILIENCE_RETRY_BASE_BACKOFF",
        "RESILIENCE_RETRY_MAX_BACKOFF",
        "RESILIENCE_RETRY_JITTER_RATIO",
    ):
        monkeypatch.delenv(k, raising=False)
    p = RetryPolicy.from_env()
    assert p.max_attempts == 3
    assert p.base_backoff_seconds == 0.5


def test_from_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESILIENCE_RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("RESILIENCE_RETRY_BASE_BACKOFF", "1.5")
    p = RetryPolicy.from_env()
    assert p.max_attempts == 5
    assert p.base_backoff_seconds == 1.5


def test_from_env_invalid_value_falls_back(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RESILIENCE_RETRY_MAX_ATTEMPTS", "abc")
    with caplog.at_level("WARNING"):
        p = RetryPolicy.from_env()
    # 落回默认
    assert p.max_attempts == 3
    assert any("无法解析" in rec.message for rec in caplog.records)


def test_policy_is_frozen() -> None:
    p = RetryPolicy()
    with pytest.raises(Exception):
        p.max_attempts = 99  # type: ignore[misc]
