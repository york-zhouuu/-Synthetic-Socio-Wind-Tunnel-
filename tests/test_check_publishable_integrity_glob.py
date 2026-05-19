"""Bug E (fix-publishable-integrity-glob) regression test.

Verifies that `_load_seed_files` only treats real `seed_<N>.json` as
seed records, excluding auxiliary files (positions / snapshot / partial).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_minimal_seed_payload(seed: int) -> dict:
    """Minimal valid-looking seed_N.json content."""
    return {
        "multi_day_result": {"seed": seed, "per_day_summaries": []},
        "run_metrics": {"seed": seed, "variant_name": "baseline"},
    }


@pytest.fixture
def fake_suite(tmp_path: Path) -> Path:
    """Build a suite dir with mixed real + auxiliary files."""
    suite = tmp_path / "suite"
    variant = suite / "variant_baseline"
    variant.mkdir(parents=True)
    # Real seed result
    (variant / "seed_42.json").write_text(
        json.dumps(_make_minimal_seed_payload(42)),
    )
    (variant / "seed_43.json").write_text(
        json.dumps(_make_minimal_seed_payload(43)),
    )
    # Auxiliary files that previously got false-positive flagged
    (variant / "seed_42_positions.json").write_text("{}")
    (variant / "seed_42_tick3984.snapshot.json").write_text("{}")
    (variant / "seed_43_tick4008.snapshot.json").write_text("{}")
    (variant / "seed_42_day0.partial.json").write_text("{}")
    (variant / "seed_42_day11.partial.json").write_text("{}")
    return suite


def test_glob_includes_only_real_seed_json(fake_suite: Path) -> None:
    """spec: only seed_<digits>.json count as records."""
    from tools.check_publishable_integrity import _load_seed_files
    by_variant = _load_seed_files(fake_suite)
    assert "variant_baseline" in by_variant
    records = by_variant["variant_baseline"]
    # Should be exactly 2 records (seed_42.json + seed_43.json), NOT 7
    assert len(records) == 2, (
        f"expected 2 real seed records, got {len(records)}; "
        f"auxiliary files (positions / snapshot / partial) leaking through"
    )


def test_positions_file_excluded(tmp_path: Path) -> None:
    """positions_file alone (no seed result) → 0 records."""
    from tools.check_publishable_integrity import _load_seed_files
    suite = tmp_path / "s"
    v = suite / "variant_x"
    v.mkdir(parents=True)
    (v / "seed_42_positions.json").write_text("{}")
    by_variant = _load_seed_files(suite)
    # If only positions file, no real seed_N.json exists → variant key
    # not even added (since the empty list branch is skipped in impl)
    assert by_variant.get("variant_x", []) == []


def test_snapshot_file_excluded(tmp_path: Path) -> None:
    from tools.check_publishable_integrity import _load_seed_files
    suite = tmp_path / "s"
    v = suite / "variant_x"
    v.mkdir(parents=True)
    (v / "seed_42_tick3984.snapshot.json").write_text("{}")
    by_variant = _load_seed_files(suite)
    assert by_variant.get("variant_x", []) == []


def test_partial_file_excluded(tmp_path: Path) -> None:
    from tools.check_publishable_integrity import _load_seed_files
    suite = tmp_path / "s"
    v = suite / "variant_x"
    v.mkdir(parents=True)
    (v / "seed_42_day0.partial.json").write_text("{}")
    by_variant = _load_seed_files(suite)
    assert by_variant.get("variant_x", []) == []
