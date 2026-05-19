"""Layer 1 — RetryPolicy class-name property tests (Phase G4).

Hypothesis: random ASCII class names NOT in default set SHALL always
return "unknown" (or "retryable" only via Python builtin isinstance path).
Catches regression where a typo / overly broad rule lets random names
slip through.
"""

from __future__ import annotations

import string
from typing import Type

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from synthetic_socio_wind_tunnel.run_resilience.retry import RetryPolicy


_DEFAULT_NAMES_GUESSES = frozenset({
    "APIConnectionError", "APITimeoutError",
    "ConnectError", "ReadError", "WriteError",
    "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout",
    "RemoteProtocolError",
    "DeadlineExceeded", "ServiceUnavailable",
    # Python builtins (would still be classified via type check)
    "TimeoutError", "ConnectionError",
})


def _make_exc_class(name: str) -> Type[Exception]:
    """Create an Exception subclass with the given name."""
    return type(name, (Exception,), {})


@given(st.text(
    alphabet=string.ascii_letters,
    min_size=3,
    max_size=20,
))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_random_class_names_not_in_default_set_return_unknown(
    name: str,
) -> None:
    """Random class names not in default SHALL classify as 'unknown'.

    This guards against accidentally broadening the class-name set
    (e.g., via greedy regex / substring match instead of equality).
    """
    if name in _DEFAULT_NAMES_GUESSES:
        return  # skip — these are intentionally retryable
    if name.endswith("Error") and name in _DEFAULT_NAMES_GUESSES:
        return
    # If the name happens to collide with an isinstance-retryable type's
    # name (e.g. "TimeoutError"), skip too
    if name in ("OSError",):  # OSError parent of ConnectionError builtin
        return

    cls = _make_exc_class(name)
    exc = cls("synthetic")
    policy = RetryPolicy()
    verdict = policy.classify(exc)
    assert verdict == "unknown", (
        f"random class name {name!r} unexpectedly classified as {verdict}"
    )


def test_policy_frozen_invariant_under_classify() -> None:
    """100 classify calls SHALL NOT mutate policy fields (frozen invariant)."""
    policy = RetryPolicy()
    initial_class_names = policy.retryable_exc_class_names
    initial_retryable_excs = policy.retryable_exceptions
    initial_max_attempts = policy.max_attempts

    for _ in range(100):
        policy.classify(RuntimeError("x"))
        policy.classify(ConnectionError("y"))

    assert policy.retryable_exc_class_names == initial_class_names
    assert policy.retryable_exceptions == initial_retryable_excs
    assert policy.max_attempts == initial_max_attempts
