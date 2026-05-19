"""Layer 6 fault injection — env switch falls back to legacy path.

Spec: `MEMORY_SNAPSHOT_USE_FAST=0` SHALL route `_event_to_json` to the
legacy implementation. This guards the rollback path.
"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import patch

import pytest

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
from synthetic_socio_wind_tunnel.memory import service as _svc


def _make_event() -> MemoryEvent:
    return MemoryEvent(
        event_id="ev_test_001", agent_id="a_test", tick=10,
        simulated_time=datetime(2026, 4, 22, 8, 0),
        kind="action", content="test content",
        importance=0.5,
    )


@pytest.fixture(autouse=True)
def clean_env() -> None:
    """Strip MEMORY_SNAPSHOT_USE_FAST from env so per-test sets are clean."""
    old = os.environ.pop("MEMORY_SNAPSHOT_USE_FAST", None)
    yield
    if old is not None:
        os.environ["MEMORY_SNAPSHOT_USE_FAST"] = old


def test_env_set_to_zero_routes_to_legacy() -> None:
    """With MEMORY_SNAPSHOT_USE_FAST=0, _event_to_json SHALL call legacy."""
    legacy = getattr(_svc, "_event_to_json_legacy", None)
    fast = getattr(_svc, "_event_to_json_fast", None)
    if legacy is None or fast is None:
        pytest.skip("G4 not landed: legacy/fast impls don't exist yet")

    os.environ["MEMORY_SNAPSHOT_USE_FAST"] = "0"

    # Patch the legacy impl so we can detect it was called
    called = {"legacy": 0, "fast": 0}

    def _spy_legacy(ev):
        called["legacy"] += 1
        return legacy(ev)

    def _spy_fast(ev):
        called["fast"] += 1
        return fast(ev)

    with patch.object(_svc, "_event_to_json_legacy", side_effect=_spy_legacy), \
         patch.object(_svc, "_event_to_json_fast", side_effect=_spy_fast):
        _svc._event_to_json(_make_event())

    assert called["legacy"] == 1
    assert called["fast"] == 0


def test_env_default_routes_to_fast() -> None:
    """Default (env unset or =1): SHALL call fast path."""
    legacy = getattr(_svc, "_event_to_json_legacy", None)
    fast = getattr(_svc, "_event_to_json_fast", None)
    if legacy is None or fast is None:
        pytest.skip("G4 not landed")

    # env unset
    os.environ.pop("MEMORY_SNAPSHOT_USE_FAST", None)

    called = {"legacy": 0, "fast": 0}

    def _spy_legacy(ev):
        called["legacy"] += 1
        return legacy(ev)

    def _spy_fast(ev):
        called["fast"] += 1
        return fast(ev)

    with patch.object(_svc, "_event_to_json_legacy", side_effect=_spy_legacy), \
         patch.object(_svc, "_event_to_json_fast", side_effect=_spy_fast):
        _svc._event_to_json(_make_event())

    assert called["legacy"] == 0
    assert called["fast"] == 1
