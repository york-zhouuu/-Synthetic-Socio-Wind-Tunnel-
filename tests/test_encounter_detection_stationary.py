"""Tests for B9: encounter detection includes stationary co-located agents.

Original `_detect_encounters` only consulted TickMovementTrace, which
captures only agents who moved (issued MoveIntent and successfully walked).
Stationary agents (WaitIntent / dwell at a location) were invisible →
encounters during dwell windows were systematically undercounted.

Fix: encounter detection takes a second input `entity_locations` from
the Ledger snapshot at tick-end and merges it into the per-location
bucket alongside trace-based locations.
"""

from __future__ import annotations

from synthetic_socio_wind_tunnel.orchestrator.models import TickMovementTrace
from synthetic_socio_wind_tunnel.orchestrator.service import Orchestrator


def _detect(traces: dict, entity_locations: dict | None = None):
    """Call the static method via Orchestrator instance helper."""
    # _detect_encounters is a method but doesn't read self state for the bucket
    # algorithm. Construct a minimal-state Orchestrator just for the call.
    # Easier: monkey-create the bound method by calling on the unbound
    # using Orchestrator.__dict__["_detect_encounters"] with self=None
    # — but that requires no self access. Quick test: it doesn't access self.
    # So we can call it as an unbound method.
    fn = Orchestrator._detect_encounters
    return fn(None, tick_index=42, traces=traces, entity_locations=entity_locations)


class TestStationaryCoPresence:

    def test_two_stationary_at_same_location(self):
        """B9 core scenario: 2 dwelling agents at cafe → 1 encounter."""
        traces: dict = {}  # neither moved
        entity_locations = {"alpha": "cafe_a", "beta": "cafe_a"}
        candidates = _detect(traces, entity_locations)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.agent_a == "alpha"
        assert c.agent_b == "beta"
        assert c.shared_locations == ("cafe_a",)
        assert c.tick == 42

    def test_two_stationary_at_different_locations(self):
        """No encounter when locations differ."""
        traces: dict = {}
        entity_locations = {"alpha": "cafe_a", "beta": "park_b"}
        candidates = _detect(traces, entity_locations)
        assert candidates == []

    def test_walking_through_plus_stationary(self):
        """Walking agent meets stationary one at the shared location."""
        traces = {
            "beta": TickMovementTrace(locations=("street_1", "cafe_a")),
        }
        # alpha is dwelling at cafe_a
        entity_locations = {"alpha": "cafe_a", "beta": "cafe_a"}
        candidates = _detect(traces, entity_locations)
        assert len(candidates) == 1
        assert candidates[0].agent_a == "alpha"
        assert candidates[0].agent_b == "beta"
        assert "cafe_a" in candidates[0].shared_locations

    def test_three_stationary_at_same_location(self):
        """C(3,2) = 3 pairs all at same location."""
        traces: dict = {}
        entity_locations = {
            "alpha": "park", "beta": "park", "gamma": "park",
        }
        candidates = _detect(traces, entity_locations)
        assert len(candidates) == 3
        # All pairs sorted lexically (a,b), (a,g), (b,g)
        pairs = {(c.agent_a, c.agent_b) for c in candidates}
        assert pairs == {
            ("alpha", "beta"), ("alpha", "gamma"), ("beta", "gamma"),
        }
        for c in candidates:
            assert c.shared_locations == ("park",)

    def test_dedup_when_trace_and_stationary_overlap(self):
        """Agent moved INTO cafe (trace ends at cafe) AND ledger says they're
        at cafe → SHALL produce 1 pair (not 2)."""
        traces = {
            "alpha": TickMovementTrace(locations=("street_1", "cafe_a")),
        }
        entity_locations = {"alpha": "cafe_a", "beta": "cafe_a"}
        candidates = _detect(traces, entity_locations)
        assert len(candidates) == 1
        assert candidates[0].shared_locations == ("cafe_a",)

    def test_no_traces_no_locations_returns_empty(self):
        candidates = _detect({}, None)
        assert candidates == []
        candidates = _detect({}, {})
        assert candidates == []

    def test_stationary_with_blank_location_ignored(self):
        """Empty/None location entries SHALL NOT crash or produce candidates."""
        entity_locations = {"alpha": "", "beta": "cafe_a"}
        candidates = _detect({}, entity_locations)
        # alpha skipped due to empty location → only beta in bucket → 0 pairs
        assert candidates == []

    def test_legacy_trace_only_path_still_works(self):
        """Backwards compat: not passing entity_locations SHALL behave as
        original trace-only detection."""
        traces = {
            "alpha": TickMovementTrace(locations=("cafe_a",)),
            "beta": TickMovementTrace(locations=("cafe_a",)),
        }
        candidates = _detect(traces, entity_locations=None)
        assert len(candidates) == 1
        assert candidates[0].shared_locations == ("cafe_a",)


class TestPerTickCounting:
    """Per-tick co-presence count is preserved (not deduplicated across ticks)."""

    def test_each_tick_emits_separate_candidate(self):
        """Two stationary at cafe across multiple ticks: each tick gets a candidate."""
        entity_locations = {"alpha": "cafe_a", "beta": "cafe_a"}

        def call_at_tick(t):
            return Orchestrator._detect_encounters(
                None, tick_index=t, traces={}, entity_locations=entity_locations,
            )

        c0 = call_at_tick(0)
        c1 = call_at_tick(1)
        c2 = call_at_tick(2)
        assert all(len(cs) == 1 for cs in (c0, c1, c2))
        assert c0[0].tick == 0
        assert c1[0].tick == 1
        assert c2[0].tick == 2
