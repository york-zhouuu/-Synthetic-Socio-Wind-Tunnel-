"""Tests for PositionTraceRecorder."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.metrics.position_trace import (
    PositionChange,
    PositionTraceRecorder,
)
from synthetic_socio_wind_tunnel.orchestrator.models import TickResult


def _tick(tick_index: int, day_index: int, locations: dict[str, str]) -> TickResult:
    return TickResult(
        tick_index=tick_index,
        simulated_time=datetime(2026, 5, 13, 0, 0),
        commits=(),
        encounter_candidates=(),
        day_index=day_index,
        entity_locations=tuple(locations.items()),
    )


def test_no_change_no_record():
    rec = PositionTraceRecorder()
    rec.on_tick_end(_tick(0, 0, {"a": "home"}))
    rec.on_tick_end(_tick(1, 0, {"a": "home"}))
    assert rec.total_changes == 1


def test_changes_recorded():
    rec = PositionTraceRecorder()
    rec.on_tick_end(_tick(0, 0, {"a": "home", "b": "home"}))
    rec.on_tick_end(_tick(1, 0, {"a": "cafe", "b": "home"}))
    rec.on_tick_end(_tick(2, 0, {"a": "cafe", "b": "park"}))
    # initial 2 records (home, home), then a→cafe, then b→park = 4 total
    assert rec.total_changes == 4


def test_serialization(tmp_path: Path):
    rec = PositionTraceRecorder()
    rec.on_tick_end(_tick(0, 0, {"a": "home"}))
    rec.on_tick_end(_tick(5, 0, {"a": "cafe"}))
    out_file = tmp_path / "positions.json"
    rec.write(out_file)
    data = json.loads(out_file.read_text())
    assert data["schema"] == "position_trace_v1"
    assert data["n_changes"] == 2
    assert data["changes"][0]["agent_id"] == "a"
    assert data["changes"][0]["location_id"] == "home"
    assert data["changes"][1]["location_id"] == "cafe"


def test_empty_location_ignored():
    rec = PositionTraceRecorder()
    rec.on_tick_end(_tick(0, 0, {"a": ""}))
    assert rec.total_changes == 0


def test_multi_day(tmp_path: Path):
    rec = PositionTraceRecorder()
    rec.on_tick_end(_tick(0, 0, {"a": "home"}))
    rec.on_tick_end(_tick(288, 1, {"a": "cafe"}))
    rec.on_tick_end(_tick(576, 2, {"a": "home"}))
    data = rec.to_dict()
    assert data["changes"][0]["day"] == 0
    assert data["changes"][1]["day"] == 1
    assert data["changes"][2]["day"] == 2
