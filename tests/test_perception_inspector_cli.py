"""Smoke tests for tools/agent_perception_inspector.py CLI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def test_cli_with_valid_agent_runs(capsys):
    """Smoke: with a valid Lane Cove location, CLI runs and prints sections."""
    from agent_perception_inspector import main  # type: ignore

    # Pick any outdoor area from the cached atlas as --location
    from synthetic_socio_wind_tunnel.cartography.lanecove import (
        create_atlas_from_osm,
    )
    atlas = create_atlas_from_osm()
    valid_loc = atlas.list_outdoor_areas()[0]

    rc = main([
        "--seed", "42",
        "--agent", "a_42_0001",
        "--day", "0",
        "--tick", "0",
        "--location", valid_loc,
    ])
    captured = capsys.readouterr()
    assert rc == 0, f"CLI exit != 0; stderr: {captured.err}"
    # Header
    assert "a_42_0001 @ day 0 tick 0" in captured.out
    # Sections
    assert "Location:" in captured.out
    assert "JSON:" in captured.out


def test_cli_invalid_location_fails_with_message(capsys):
    """Bad location → exit ≠ 0 + actionable stderr."""
    from agent_perception_inspector import main  # type: ignore

    rc = main([
        "--seed", "42",
        "--agent", "a_42_0001",
        "--day", "0",
        "--tick", "0",
        "--location", "nonexistent_loc_xyz",
    ])
    captured = capsys.readouterr()
    assert rc != 0
    assert "nonexistent_loc_xyz" in captured.err or "atlas" in captured.err.lower()


def test_cli_empty_agent_fails(capsys):
    """Empty --agent → actionable error."""
    from agent_perception_inspector import main  # type: ignore

    rc = main([
        "--seed", "42",
        "--agent", "   ",
        "--day", "0",
        "--tick", "0",
    ])
    captured = capsys.readouterr()
    assert rc != 0
    assert "agent" in captured.err.lower()
