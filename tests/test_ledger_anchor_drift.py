"""R4 (2026-05-21): ledger.current_time anchor + drift detection.

2026-05-20 scout: watchdog-respawned worker resumed from snapshot
where ledger.current_time was at day 1 22:00 ish, while
orchestrator's day_index=0 loop continued. Day_index and sim_time
drifted apart — no signal to the operator that the calendar
alignment was broken.

Fix: SimulationCheckpoint carries `start_date_anchor_iso`. Resume
compares (anchor + day_index*24h + tick_index*5min) vs actual
ledger.current_time. Warn if diff > 1h.

Tests verify:
- New write captures start_date_anchor_iso correctly
- Legacy snapshot without anchor field loads without error
- Resume with drifted ledger logs warning
- Resume with synced ledger emits NO warning
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
    SimulationCheckpoint,
)


def _minimal_snapshot_payload(
    *, day_index: int, tick_index: int,
    ledger_current_time_iso: str,
    start_date_anchor_iso: str | None = None,
    seed: int = 42,
) -> dict:
    payload = {
        "schema_version": "3",
        "seed": seed,
        "day_index": day_index,
        "tick_index": tick_index,
        "simulated_time": ledger_current_time_iso,
        "created_at": "2026-05-21T00:00:00",
        "provider": "stub",
        "ledger_state": {
            "entities": {}, "items": {},
            "current_time": ledger_current_time_iso,
        },
        "agent_runtime_states": {},
        "memory_store_state": {},
        "attention_service_state": {},
        "tick_metrics_recorder_state": {},
        "dialogue_service_state": {},
        "rng_state": {},
        "pending_ops_meta": {},
    }
    if start_date_anchor_iso is not None:
        payload["start_date_anchor_iso"] = start_date_anchor_iso
    return payload


def test_snapshot_field_round_trips(tmp_path: Path):
    """SimulationCheckpoint with start_date_anchor_iso SHALL round-trip
    write → read losslessly."""
    p = tmp_path / "test.snapshot.json"
    payload = _minimal_snapshot_payload(
        day_index=0, tick_index=12,
        ledger_current_time_iso="2026-04-22T01:00:00",
        start_date_anchor_iso="2026-04-22",
    )
    p.write_text(json.dumps(payload))

    snap = SimulationCheckpoint.read(p)
    assert snap.start_date_anchor_iso == "2026-04-22"


def test_legacy_snapshot_no_anchor_back_compat(tmp_path: Path):
    """v3 snapshot WITHOUT start_date_anchor_iso SHALL load with field=None."""
    p = tmp_path / "legacy.snapshot.json"
    payload = _minimal_snapshot_payload(
        day_index=0, tick_index=12,
        ledger_current_time_iso="2026-04-22T01:00:00",
        start_date_anchor_iso=None,  # explicitly omit
    )
    # Even sanity-strip the key to simulate true legacy
    if "start_date_anchor_iso" in payload:
        del payload["start_date_anchor_iso"]
    p.write_text(json.dumps(payload))

    snap = SimulationCheckpoint.read(p)
    assert snap.start_date_anchor_iso is None


def test_drift_detection_logs_warning(tmp_path: Path, caplog):
    """When resume sees ledger drifted from (anchor + day*24h + tick*5min)
    by >1h, a WARNING SHALL be logged."""
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayRunner

    p = tmp_path / "drifted.snapshot.json"
    # Anchor day 0 + 0 ticks → expected ledger = day 0 00:00
    # Actual ledger = day 0 23:00 → drift = 23 hours
    payload = _minimal_snapshot_payload(
        day_index=0, tick_index=0,
        ledger_current_time_iso="2026-04-22T23:00:00",
        start_date_anchor_iso="2026-04-22",
    )
    p.write_text(json.dumps(payload))

    snap = SimulationCheckpoint.read(p)
    with caplog.at_level(logging.WARNING):
        # Directly call the helper (don't spin up full runner machinery)
        MultiDayRunner._check_ledger_drift_static(
            snap=snap, configured_start_date=date(2026, 4, 22),
        )

    assert any("drift" in r.message.lower() for r in caplog.records), (
        f"Expected drift warning, got: {[r.message for r in caplog.records]}"
    )


def test_no_drift_no_warning(tmp_path: Path, caplog):
    """When ledger matches expected (anchor + day*24h + tick*5min), no warning."""
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayRunner

    p = tmp_path / "synced.snapshot.json"
    # Anchor day 0 + tick 12 → expected ledger = day 0 + 12*5min = 01:00
    payload = _minimal_snapshot_payload(
        day_index=0, tick_index=12,
        ledger_current_time_iso="2026-04-22T01:00:00",
        start_date_anchor_iso="2026-04-22",
    )
    p.write_text(json.dumps(payload))

    snap = SimulationCheckpoint.read(p)
    with caplog.at_level(logging.WARNING):
        MultiDayRunner._check_ledger_drift_static(
            snap=snap, configured_start_date=date(2026, 4, 22),
        )
    # No drift warnings
    assert not any("drift" in r.message.lower() for r in caplog.records)


def test_no_anchor_skips_drift_check(tmp_path: Path, caplog):
    """Legacy snapshot (anchor=None) SHALL silently skip drift detection."""
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayRunner

    p = tmp_path / "legacy.snapshot.json"
    payload = _minimal_snapshot_payload(
        day_index=0, tick_index=0,
        ledger_current_time_iso="2026-04-22T23:00:00",
        start_date_anchor_iso=None,
    )
    if "start_date_anchor_iso" in payload:
        del payload["start_date_anchor_iso"]
    p.write_text(json.dumps(payload))

    snap = SimulationCheckpoint.read(p)
    with caplog.at_level(logging.WARNING):
        MultiDayRunner._check_ledger_drift_static(
            snap=snap, configured_start_date=date(2026, 4, 22),
        )
    assert not any("drift" in r.message.lower() for r in caplog.records)
