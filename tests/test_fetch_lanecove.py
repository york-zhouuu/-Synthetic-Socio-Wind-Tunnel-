"""Tests for tools/fetch_lanecove.py — multipolygon ring assembly."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add tools/ to import path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from fetch_lanecove import _assemble_outer_rings  # type: ignore


class TestAssembleOuterRings:

    def test_simple_rectangle_from_4_open_ways(self):
        """4 segments forming a rectangle, each is open → assembled to 1 ring."""
        # Rectangle corners: 1 (top-left), 2 (top-right), 3 (bottom-right), 4 (bottom-left)
        ways = [
            [1, 2],     # top edge
            [2, 3],     # right edge
            [3, 4],     # bottom edge
            [4, 1],     # left edge
        ]
        rings = _assemble_outer_rings(ways, rel_id=42)
        assert len(rings) == 1
        ring = rings[0]
        assert ring[0] == ring[-1]
        assert set(ring) == {1, 2, 3, 4}

    def test_already_closed_single_way(self):
        """One way that's already closed (start == end) → 1 ring."""
        ways = [[10, 11, 12, 13, 10]]
        rings = _assemble_outer_rings(ways, rel_id=43)
        assert len(rings) == 1
        assert rings[0] == [10, 11, 12, 13, 10]

    def test_broken_chain_dropped(self, capsys):
        """Missing a way → chain can't close → drop + warning."""
        ways = [
            [1, 2],
            [2, 3],
            # [3, 4] missing
            [4, 1],
        ]
        rings = _assemble_outer_rings(ways, rel_id=99)
        assert rings == []
        captured = capsys.readouterr()
        assert "unclosed multipolygon" in captured.out
        assert "99" in captured.out

    def test_multiple_independent_rings(self):
        """Two separate closed rings → 2 outputs."""
        ways = [
            # Ring A
            [1, 2], [2, 3], [3, 1],
            # Ring B (disjoint)
            [10, 11], [11, 12], [12, 10],
        ]
        rings = _assemble_outer_rings(ways, rel_id=50)
        assert len(rings) == 2
        ring_node_sets = [set(r) for r in rings]
        assert {1, 2, 3} in ring_node_sets
        assert {10, 11, 12} in ring_node_sets

    def test_way_appended_in_reverse_when_endpoint_matches(self):
        """If next way's END (not start) matches tail, it should be reversed."""
        ways = [
            [1, 2],     # chain so far ends at 2
            [3, 2],     # tail 2 == this.end(2) → reverse → use [2, 3]
            [3, 4],
            [4, 1],
        ]
        rings = _assemble_outer_rings(ways, rel_id=60)
        assert len(rings) == 1
        ring = rings[0]
        assert ring[0] == ring[-1]
        assert set(ring) == {1, 2, 3, 4}

    def test_lane_cove_river_scenario(self):
        """
        Synthetic version of Lane Cove River: many open segments forming one
        large ring. Validates the algorithm scales.
        """
        # 20-segment ring: nodes 0..19 then back to 0
        ways = [[i, (i + 1) % 20] for i in range(20)]
        rings = _assemble_outer_rings(ways, rel_id=12345)
        assert len(rings) == 1
        assert len(rings[0]) == 21  # 20 nodes + closing repeat
        assert rings[0][0] == rings[0][-1]

    def test_empty_input(self):
        assert _assemble_outer_rings([], rel_id=1) == []

    def test_too_short_ways_filtered(self):
        ways = [[1], [2]]  # single-node "ways" filtered
        assert _assemble_outer_rings(ways, rel_id=2) == []
