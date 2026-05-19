"""Layer 3 — malloc_zone_pressure_relief fault injection.

Spec: openspec/specs/run-resilience/spec.md
Requirement: "gc.collect() 后必须调 malloc_zone_pressure_relief"

The helper SHALL NEVER crash the run; failures fallback silently after
one warning.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


def _get_helper():
    """Import the pressure_relief helper (added by G5)."""
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import (
        _call_malloc_pressure_relief,
    )
    return _call_malloc_pressure_relief


def test_helper_exists() -> None:
    """G5 SHALL add `_call_malloc_pressure_relief` to multi_day module."""
    helper = _get_helper()
    assert callable(helper)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only path")
def test_macos_real_invocation_does_not_raise() -> None:
    """spec scenario: macOS 调用成功."""
    helper = _get_helper()
    # Just call it. SHALL NOT raise.
    helper()  # If it returned anything, that's fine — we just want no exception


def test_ctypes_load_failure_fallback() -> None:
    """spec scenario: ctypes 调用失败 fallback."""
    helper = _get_helper()
    with patch("ctypes.CDLL", side_effect=OSError("simulated lib load fail")):
        # Must not crash
        helper()
        helper()  # second call also OK (should be silent after first warn)


def test_call_attribute_missing_fallback() -> None:
    """spec scenario: 平台不支持 malloc_zone_pressure_relief 符号."""
    helper = _get_helper()

    # Build a fake CDLL whose attribute lookup raises AttributeError
    class _FakeLib:
        def __getattr__(self, name):
            raise AttributeError(f"libc has no {name!r}")

    with patch("ctypes.CDLL", return_value=_FakeLib()):
        helper()  # should not raise


def test_multiple_calls_warn_only_once(caplog) -> None:
    """spec: 第一次失败 log warning，后续 silent."""
    helper = _get_helper()
    # Reset any global state used by helper
    from synthetic_socio_wind_tunnel.orchestrator import multi_day as md
    if hasattr(md, "_pressure_relief_disabled"):
        md._pressure_relief_disabled = False

    with patch("ctypes.CDLL", side_effect=OSError("fail")):
        import logging
        with caplog.at_level(logging.WARNING):
            helper()
            helper()
            helper()
        # Should produce <= 1 warning (silent after disable flag set)
        warnings = [r for r in caplog.records if "malloc" in r.message.lower()]
        assert len(warnings) <= 1
