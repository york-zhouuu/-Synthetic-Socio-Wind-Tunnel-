"""backlog 1.7 E (2026-05-20): MemoryEvent slots regression guard.

Protects the 500MB-1GB-RSS saving on publishable scale by enforcing
the slots invariant. If someone later removes `slots=True` from the
@dataclass decorator (silent code review miss), this test catches it.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.memory.models import (
    DailySummary, MemoryEvent, MemoryQuery,
)


def test_memory_event_has_slots():
    """MemoryEvent SHALL define __slots__ (not __dict__).

    AttributeError on .__dict__ access is the diagnostic — slot classes
    don't allocate a per-instance dict, which is what saves the RAM.
    """
    ev = MemoryEvent(
        event_id="e1", agent_id="a1", tick=0,
        simulated_time=datetime(2026, 5, 20),
        kind="action", content="x",
    )
    # Slot dataclasses expose __slots__ as the class-level field list
    assert hasattr(type(ev), "__slots__")
    # And SHALL NOT have a per-instance __dict__
    with pytest.raises(AttributeError):
        _ = ev.__dict__


def test_memory_event_attribute_set_rejected():
    """Frozen + slots SHALL forbid both mutation AND new attribute add."""
    ev = MemoryEvent(
        event_id="e1", agent_id="a1", tick=0,
        simulated_time=datetime(2026, 5, 20),
        kind="action", content="x",
    )
    # frozen=True path: dataclasses.FrozenInstanceError on existing fields
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.event_id = "tampered"
    # slots path: assignment of unknown attr SHALL fail. Frozen + slots
    # in CPython 3.11 raises the FrozenInstanceError path first
    # (before slot validation), so accept either error type.
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError, TypeError)):
        ev.unknown_field = "no slot for this"


def test_memory_query_has_slots():
    q = MemoryQuery()
    assert hasattr(type(q), "__slots__")
    with pytest.raises(AttributeError):
        _ = q.__dict__


def test_daily_summary_has_slots():
    s = DailySummary(agent_id="a1", date="2026-05-20", summary_text="x")
    assert hasattr(type(s), "__slots__")
    with pytest.raises(AttributeError):
        _ = s.__dict__
