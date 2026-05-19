"""Layer 1 — RetryPolicy.from_env class-name override (Phase G3).

Spec: openspec/specs/run-resilience/spec.md
Requirement: "env override 追加自定义 class names"
"""

from __future__ import annotations

import logging

import pytest

from synthetic_socio_wind_tunnel.run_resilience.retry import RetryPolicy


def test_env_override_appends_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spec scenario: 追加自定义 class name (union with defaults)."""
    monkeypatch.setenv(
        "RESILIENCE_RETRY_EXC_CLASS_NAMES",
        "MyCustomError,AnotherErr",
    )
    policy = RetryPolicy.from_env()
    # Default 12 + 2 custom = 14
    assert "MyCustomError" in policy.retryable_exc_class_names
    assert "AnotherErr" in policy.retryable_exc_class_names
    # Defaults still present
    assert "APIConnectionError" in policy.retryable_exc_class_names
    assert "ConnectError" in policy.retryable_exc_class_names


def test_empty_env_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """spec scenario: env 为空时使用默认值 (12 elements)."""
    monkeypatch.delenv("RESILIENCE_RETRY_EXC_CLASS_NAMES", raising=False)
    policy_unset = RetryPolicy.from_env()

    monkeypatch.setenv("RESILIENCE_RETRY_EXC_CLASS_NAMES", "")
    policy_empty = RetryPolicy.from_env()

    # Both SHALL have exactly the default frozenset (12 names per spec)
    assert policy_unset.retryable_exc_class_names == \
           policy_empty.retryable_exc_class_names
    assert len(policy_unset.retryable_exc_class_names) == 12


def test_whitespace_trimmed_per_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Names with surrounding whitespace SHALL be stripped."""
    monkeypatch.setenv(
        "RESILIENCE_RETRY_EXC_CLASS_NAMES",
        " ErrA ,  ErrB  ,ErrC",
    )
    policy = RetryPolicy.from_env()
    assert "ErrA" in policy.retryable_exc_class_names
    assert "ErrB" in policy.retryable_exc_class_names
    assert "ErrC" in policy.retryable_exc_class_names
    # No stray whitespace versions
    assert " ErrA " not in policy.retryable_exc_class_names
    assert "  ErrB  " not in policy.retryable_exc_class_names


def test_empty_strings_filtered(monkeypatch: pytest.MonkeyPatch) -> None:
    """`,,,` between commas SHALL be filtered as empty."""
    monkeypatch.setenv(
        "RESILIENCE_RETRY_EXC_CLASS_NAMES",
        ",ErrA,,ErrB,",
    )
    policy = RetryPolicy.from_env()
    assert "ErrA" in policy.retryable_exc_class_names
    assert "ErrB" in policy.retryable_exc_class_names
    assert "" not in policy.retryable_exc_class_names


def test_default_classnames_count_matches_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spec: 默认 frozenset 恰好 12 元素，覆盖 4 类 SDK."""
    monkeypatch.delenv("RESILIENCE_RETRY_EXC_CLASS_NAMES", raising=False)
    policy = RetryPolicy.from_env()
    names = policy.retryable_exc_class_names
    # 12 names from spec
    assert len(names) == 12
    # Spot-check each SDK family is represented
    assert "APIConnectionError" in names  # openai + anthropic
    assert "APITimeoutError" in names
    assert "ConnectError" in names  # httpx
    assert "ReadTimeout" in names
    assert "RemoteProtocolError" in names
    assert "DeadlineExceeded" in names  # google-genai
    assert "ServiceUnavailable" in names
