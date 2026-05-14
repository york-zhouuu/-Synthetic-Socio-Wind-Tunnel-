"""Tests for tools/audit_dwell_distribution.py acceptance thresholds."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from audit_dwell_distribution import audit  # type: ignore

from synthetic_socio_wind_tunnel import Atlas


@pytest.fixture(scope="module")
def lc_atlas() -> Atlas:
    return Atlas.from_json("data/lanecove_atlas.json")


def _write_seed(tmp_path: Path, space_activation: dict[str, float]) -> Path:
    seed = {
        "run_metrics": {
            "space_activation": space_activation,
        },
    }
    seed_file = tmp_path / "seed_42.json"
    seed_file.write_text(json.dumps(seed))
    return seed_file


def test_high_residential_passes(lc_atlas: Atlas, tmp_path: Path) -> None:
    residentials = [b.id for b in lc_atlas.list_residential_buildings()[:5]]
    if len(residentials) < 5:
        pytest.skip("not enough residential buildings in atlas")
    sp = {rid: 1000.0 for rid in residentials}
    sp[residentials[0]] = 5000.0  # bump residential weight
    seed = _write_seed(tmp_path, sp)
    passed, _, shares = audit(seed, lc_atlas)
    assert passed, f"high residential should pass: shares={shares}"
    assert shares["residential"] >= 0.40


def test_high_street_fails(lc_atlas: Atlas, tmp_path: Path) -> None:
    streets = [a.id for a in lc_atlas.region.outdoor_areas.values()
               if a.is_street][:5]
    if len(streets) < 5:
        pytest.skip("not enough streets in atlas")
    sp = {sid: 10000.0 for sid in streets}
    seed = _write_seed(tmp_path, sp)
    passed, _, shares = audit(seed, lc_atlas)
    assert not passed, f"high street should fail: shares={shares}"
    assert shares["street"] > 0.20


def test_empty_space_activation_raises(lc_atlas: Atlas, tmp_path: Path) -> None:
    seed = _write_seed(tmp_path, {})
    with pytest.raises(ValueError, match="empty space_activation"):
        audit(seed, lc_atlas)


def test_zero_total_raises(lc_atlas: Atlas, tmp_path: Path) -> None:
    residential = lc_atlas.list_residential_buildings()[0].id
    seed = _write_seed(tmp_path, {residential: 0.0})
    with pytest.raises(ValueError, match="total dwell == 0"):
        audit(seed, lc_atlas)
