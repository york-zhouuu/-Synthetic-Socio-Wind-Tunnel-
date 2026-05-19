"""Unit tests for tools/audit_resume_strategies.py.

Spec: each `_scan_cell` decision branch should map to the correct
`recommended_strategy` per CLAUDE.md sigusr1-graceful-stop-corruption
invariant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.audit_resume_strategies import _scan_cell


def _make_cell(
    base: Path, seed: int, variant: str,
    *,
    snapshots: list[int] = (),
    partials: list[int] = (),
    has_wal: bool = False,
    has_seed_json: bool = False,
    quarantined: list[str] = (),
) -> Path:
    """Build a cell directory layout for testing."""
    vdir = base / f"variant_{variant}"
    vdir.mkdir(parents=True, exist_ok=True)
    for tick in snapshots:
        (vdir / f"seed_{seed}_tick{tick}.snapshot.json").write_text("{}")
    for day in partials:
        (vdir / f"seed_{seed}_day{day}.partial.json").write_text("{}")
    if has_wal:
        (vdir / f"seed_{seed}.wal.jsonl").write_text("")
    if has_seed_json:
        (vdir / f"seed_{seed}.json").write_text("{}")
    for q in quarantined:
        (vdir / q).write_text("{}")
    return base


def test_done_cell_returns_skip(tmp_path: Path) -> None:
    """seed_N.json present → DONE → skip."""
    _make_cell(tmp_path, 42, "baseline", has_seed_json=True)
    row = _scan_cell(tmp_path, 42, "baseline")
    assert row["state"] == "DONE"
    assert row["recommended_strategy"] == "skip"


def test_snapshot_and_partial_returns_auto(tmp_path: Path) -> None:
    """Both present → INTERRUPTED → auto safe."""
    _make_cell(
        tmp_path, 42, "phone_friction",
        snapshots=[3444], partials=[0, 1, 2, 11], has_wal=True,
    )
    row = _scan_cell(tmp_path, 42, "phone_friction")
    assert row["state"] == "INTERRUPTED"
    assert row["recommended_strategy"] == "auto"
    assert row["latest_snapshot_tick"] == 3444
    assert row["latest_partial_day"] == 11


def test_snapshot_only_with_quarantine_returns_snapshot_only(
    tmp_path: Path,
) -> None:
    """Snapshot + no partial + quarantined stub → snapshot-only with note."""
    _make_cell(
        tmp_path, 42, "hyperlocal_push",
        snapshots=[2784], has_wal=True,
        quarantined=[
            "seed_42.json.gracefulstop_stub_20260519T1204",
            "aggregate.json.gracefulstop_stub_20260519T1204",
        ],
    )
    row = _scan_cell(tmp_path, 42, "hyperlocal_push")
    assert row["state"] == "INTERRUPTED_PARTIAL_MISSING"
    assert row["recommended_strategy"] == "snapshot-only"
    assert "sigusr1-graceful-stop-corruption" in row["note"]
    assert row["quarantined_stub_count"] == 2


def test_snapshot_only_without_quarantine_still_snapshot_only(
    tmp_path: Path,
) -> None:
    """Snapshot + no partial + no quarantine → still snapshot-only.

    Reason: auto would silently fall back to day 0 if snapshot read fails.
    """
    _make_cell(
        tmp_path, 42, "phone_friction", snapshots=[2784], has_wal=True,
    )
    row = _scan_cell(tmp_path, 42, "phone_friction")
    assert row["recommended_strategy"] == "snapshot-only"
    assert "fail loudly" in row["note"]


def test_partial_only_returns_partial_only(tmp_path: Path) -> None:
    """Partials + no snapshot → partial-only."""
    _make_cell(
        tmp_path, 42, "phone_friction",
        partials=[0, 1, 2], has_wal=True,
    )
    row = _scan_cell(tmp_path, 42, "phone_friction")
    assert row["state"] == "INTERRUPTED_SNAPSHOT_MISSING"
    assert row["recommended_strategy"] == "partial-only"


def test_wal_only_returns_none(tmp_path: Path) -> None:
    """Only WAL → setup crash → start fresh."""
    _make_cell(tmp_path, 42, "phone_friction", has_wal=True)
    row = _scan_cell(tmp_path, 42, "phone_friction")
    assert row["state"] == "WAL_ONLY"
    assert row["recommended_strategy"] == "none"


def test_missing_directory_returns_none(tmp_path: Path) -> None:
    """variant dir doesn't exist → MISSING_DIR → none."""
    row = _scan_cell(tmp_path, 42, "phone_friction")
    assert row["state"] == "MISSING_DIR"
    assert row["recommended_strategy"] == "none"


def test_path_stem_double_extension_parsed_correctly(tmp_path: Path) -> None:
    """Regression: `seed_42_day0.partial.json` has stem
    `seed_42_day0.partial` (not `seed_42_day0`). Tick / day extraction
    SHALL still find the right number."""
    _make_cell(
        tmp_path, 42, "phone_friction",
        snapshots=[3444], partials=[0, 11],
    )
    row = _scan_cell(tmp_path, 42, "phone_friction")
    assert row["latest_partial_day"] == 11, (
        f"got partial_days={row['partial_days']}"
    )
    assert row["latest_snapshot_tick"] == 3444


def test_quarantined_seed_json_not_treated_as_done(tmp_path: Path) -> None:
    """The `.gracefulstop_stub_*` suffix on seed_N.json SHALL NOT count
    as DONE — only the real `seed_42.json` (no suffix) counts."""
    _make_cell(
        tmp_path, 42, "hyperlocal_push",
        snapshots=[2784],
        quarantined=["seed_42.json.gracefulstop_stub_20260519T1204"],
    )
    row = _scan_cell(tmp_path, 42, "hyperlocal_push")
    assert row["state"] != "DONE"
    assert row["recommended_strategy"] == "snapshot-only"
