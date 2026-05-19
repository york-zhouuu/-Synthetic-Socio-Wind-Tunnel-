"""Layer 1 — RetryPolicy.classify class-name path (Phase G1).

Spec: openspec/specs/run-resilience/spec.md
Requirement: "RetryPolicy.classify 异常分类 — openai.APIConnectionError 走 class name 路径"

TDD red phase: `retryable_exc_class_names` field doesn't exist yet OR is
empty by default → classify returns "unknown" for all SDK exceptions.
"""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.run_resilience.retry import RetryPolicy


def test_classify_openai_apiconnection_error_returns_retryable() -> None:
    """spec scenario: openai.APIConnectionError 走 class name 路径."""
    import openai
    exc = openai.APIConnectionError(request=None)
    policy = RetryPolicy()
    assert policy.classify(exc) == "retryable"


def test_classify_openai_apitimeout_error_returns_retryable() -> None:
    """openai.APITimeoutError SHALL be retryable."""
    import openai
    # APITimeoutError signature: APITimeoutError(request)
    exc = openai.APITimeoutError(request=None)
    policy = RetryPolicy()
    assert policy.classify(exc) == "retryable"


def test_classify_httpx_connecterror_returns_retryable() -> None:
    """spec scenario: httpx.ConnectError 走 class name 路径."""
    import httpx
    exc = httpx.ConnectError("simulated")
    policy = RetryPolicy()
    assert policy.classify(exc) == "retryable"


def test_classify_httpx_readtimeout_returns_retryable() -> None:
    """httpx.ReadTimeout SHALL be retryable."""
    import httpx
    exc = httpx.ReadTimeout("simulated read timeout")
    policy = RetryPolicy()
    assert policy.classify(exc) == "retryable"


def test_classify_httpx_remoteprotocolerror_returns_retryable() -> None:
    """spec scenario: httpx 协议中断被识别."""
    import httpx
    exc = httpx.RemoteProtocolError(
        "Server disconnected before sending response",
    )
    policy = RetryPolicy()
    assert policy.classify(exc) == "retryable"


def test_classify_runtime_error_returns_unknown() -> None:
    """spec scenario: 未知 class name 不被误判 (regression guard).

    RuntimeError doesn't match class-name set, doesn't inherit retryable
    type tuple → classify SHALL return 'unknown'.
    """
    policy = RetryPolicy()
    assert policy.classify(RuntimeError("random app error")) == "unknown"


def test_classify_fatal_http_wins_over_class_name() -> None:
    """spec scenario: fatal HTTP status 优先于 class name 命中.

    Construct a mock exception whose class name is 'APIConnectionError'
    BUT carries a status_code=401 attribute. HTTP fatal MUST win.
    """
    class APIConnectionError(Exception):  # noqa: N818
        """Mock class with same name as openai.APIConnectionError."""
        def __init__(self, status_code: int) -> None:
            super().__init__(f"401 unauthorized")
            self.status_code = status_code

    policy = RetryPolicy()
    exc = APIConnectionError(status_code=401)
    assert policy.classify(exc) == "fatal"


def test_classify_retryable_http_still_works() -> None:
    """Regression: HTTP 429 / 500 status still classified retryable."""
    class _MockStatusError(Exception):
        def __init__(self, status_code: int) -> None:
            super().__init__("")
            self.status_code = status_code

    policy = RetryPolicy()
    assert policy.classify(_MockStatusError(429)) == "retryable"
    assert policy.classify(_MockStatusError(503)) == "retryable"


def test_classify_python_builtin_connection_error_still_retryable() -> None:
    """Regression: Python builtin ConnectionError still works (isinstance path)."""
    policy = RetryPolicy()
    assert policy.classify(ConnectionError("local")) == "retryable"
    assert policy.classify(TimeoutError("local")) == "retryable"
