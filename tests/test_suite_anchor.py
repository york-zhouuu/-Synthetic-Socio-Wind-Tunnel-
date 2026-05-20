"""R5 (2026-05-21): cross-variant SUITE_ANCHOR.json.

2026-05-20 scout: 4 variants drifted because each independently
respawned by watchdog from its own (variant-specific) snapshot which
had its own ledger.current_time. No suite-level coordination existed.

Fix: first variant spawn writes `<suite_dir>/SUITE_ANCHOR.json` with
the canonical start_date. Subsequent variants verify match and use
anchor's value (defensive — operator typo can't break alignment).

Tests:
- First variant writes anchor file
- Second variant with matching start_date → silent (no warning)
- Mismatched start_date → ERROR + use anchor's value
- Corrupt anchor → WARNING + proceed with caller's start_date
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayRunner


def test_first_variant_writes_anchor(tmp_path: Path):
    """First call to read_or_write_suite_anchor SHALL create the file."""
    suite_dir = tmp_path / "suite_001"
    suite_dir.mkdir()
    result_date = MultiDayRunner._read_or_write_suite_anchor_static(
        suite_dir=suite_dir,
        configured_start_date=date(2026, 4, 22),
        configured_num_days=14,
        variant_name="baseline",
    )
    assert result_date == date(2026, 4, 22)
    anchor_path = suite_dir / "SUITE_ANCHOR.json"
    assert anchor_path.exists()
    payload = json.loads(anchor_path.read_text())
    assert payload["start_date_iso"] == "2026-04-22"
    assert payload["num_days"] == 14
    assert payload["created_by_variant"] == "baseline"


def test_second_variant_matching_anchor_silent(tmp_path: Path, caplog):
    """When start_date matches anchor, no warning/error logged."""
    suite_dir = tmp_path / "suite_002"
    suite_dir.mkdir()
    # First variant
    MultiDayRunner._read_or_write_suite_anchor_static(
        suite_dir=suite_dir,
        configured_start_date=date(2026, 4, 22),
        configured_num_days=14,
        variant_name="baseline",
    )
    # Second variant with SAME start_date
    with caplog.at_level(logging.WARNING):
        result = MultiDayRunner._read_or_write_suite_anchor_static(
            suite_dir=suite_dir,
            configured_start_date=date(2026, 4, 22),
            configured_num_days=14,
            variant_name="hyperlocal_push",
        )
    assert result == date(2026, 4, 22)
    assert not any(
        "anchor" in r.message.lower() and r.levelname in ("WARNING", "ERROR")
        for r in caplog.records
    ), f"Unexpected logs: {[(r.levelname, r.message) for r in caplog.records]}"


def test_mismatched_anchor_logs_error_uses_anchor_value(tmp_path: Path, caplog):
    """When caller's start_date != anchor's, ERROR + return anchor value."""
    suite_dir = tmp_path / "suite_003"
    suite_dir.mkdir()
    # Write anchor with 2026-04-22
    MultiDayRunner._read_or_write_suite_anchor_static(
        suite_dir=suite_dir,
        configured_start_date=date(2026, 4, 22),
        configured_num_days=14,
        variant_name="baseline",
    )
    # Second variant claims 2026-04-23 (typo or watchdog respawn with stale arg)
    with caplog.at_level(logging.ERROR):
        result = MultiDayRunner._read_or_write_suite_anchor_static(
            suite_dir=suite_dir,
            configured_start_date=date(2026, 4, 23),  # MISMATCH
            configured_num_days=14,
            variant_name="hyperlocal_push",
        )
    # Defensive: SHALL return anchor value (2026-04-22) not caller's
    assert result == date(2026, 4, 22), (
        f"Defensive: return anchor's value, got {result}"
    )
    # Loud ERROR logged
    assert any(
        r.levelname == "ERROR" and "anchor" in r.message.lower()
        for r in caplog.records
    ), f"Expected ERROR about anchor mismatch; got: {[r.message for r in caplog.records]}"


def test_corrupt_anchor_warns_proceeds(tmp_path: Path, caplog):
    """Unparseable anchor file → WARNING + return caller's start_date."""
    suite_dir = tmp_path / "suite_004"
    suite_dir.mkdir()
    # Write a corrupt anchor
    (suite_dir / "SUITE_ANCHOR.json").write_text("not json {{{")

    with caplog.at_level(logging.WARNING):
        result = MultiDayRunner._read_or_write_suite_anchor_static(
            suite_dir=suite_dir,
            configured_start_date=date(2026, 4, 22),
            configured_num_days=14,
            variant_name="baseline",
        )
    # Falls back to caller's value (no auto-correct, just proceed)
    assert result == date(2026, 4, 22)
    assert any(
        "anchor" in r.message.lower() and r.levelname == "WARNING"
        for r in caplog.records
    )
    # Corrupt file SHOULD NOT be overwritten — preserved for forensics
    assert (suite_dir / "SUITE_ANCHOR.json").read_text() == "not json {{{"
