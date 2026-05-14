"""Tests for tools/audit_realism_systemic.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from audit_realism_systemic import audit_seed  # type: ignore

from synthetic_socio_wind_tunnel import Atlas


@pytest.fixture(scope="module")
def lc_atlas() -> Atlas:
    return Atlas.from_json("data/lanecove_atlas.json")


def _write_seed(tmp_path: Path, space_activation: dict[str, float], seed: int = 42) -> Path:
    seed_data = {
        "run_metrics": {
            "seed": seed,
            "space_activation": space_activation,
        },
    }
    seed_file = tmp_path / f"seed_{seed}.json"
    seed_file.write_text(json.dumps(seed_data))
    return seed_file


def test_compliant_fixture_passes(lc_atlas: Atlas, tmp_path: Path) -> None:
    residentials = [b.id for b in lc_atlas.list_residential_buildings()[:5]]
    sp = {rid: 5000.0 for rid in residentials}
    seed = _write_seed(tmp_path, sp)
    metrics = audit_seed(seed, lc_atlas, n_agents=100)
    res_share = metrics["residential_share"][0]
    assert res_share >= 0.40, f"compliant fixture should pass residential ≥ 40%; got {res_share}"


def test_high_street_fixture_fails(lc_atlas: Atlas, tmp_path: Path) -> None:
    streets = [a.id for a in lc_atlas.region.outdoor_areas.values() if a.is_street][:5]
    sp = {sid: 10000.0 for sid in streets}
    seed = _write_seed(tmp_path, sp)
    metrics = audit_seed(seed, lc_atlas, n_agents=100)
    assert metrics["street_share"][1] is False
    assert metrics["residential_share"][1] is False


def test_audit_runs_full_check_set(lc_atlas: Atlas, tmp_path: Path) -> None:
    residentials = [b.id for b in lc_atlas.list_residential_buildings()[:5]]
    sp = {rid: 5000.0 for rid in residentials}
    seed = _write_seed(tmp_path, sp)
    metrics = audit_seed(seed, lc_atlas, n_agents=100)
    expected_keys = {
        "residential_share", "street_share", "poi_food_drink_share",
        "work_school_share", "school_pickup_real_share",
        "child_workers", "occupation_age_mismatch",
        "commute_median_m", "meals_per_day_avg",
        "household_age_gap_over_70",
    }
    assert set(metrics.keys()) == expected_keys
