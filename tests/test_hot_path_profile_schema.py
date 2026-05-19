"""Schema-level guards for the hot-path profile fixture.

These tests pin the JSON layout produced by `tools/profile_publishable_smoke.py`
and consumed by `tests/test_hot_path_baseline_regression.py`. They run
fast (no profiling, just file parsing) and SHALL be in the default CI
path.

Profile-publishable-hot-path scenarios covered:
- Requirement "提供 dev-mode profile harness" → schema_validates_handcrafted
- Requirement "落 git-tracked baseline fixture" → fixture_file_exists + fixture_satisfies_schema
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "hot_path_profile_baseline.json"


# ---- Schema validator (in-test, no external lib) ----------------------------


_REQUIRED_METADATA_KEYS = {
    "scale", "agents", "num_days", "seed", "python_version",
    "captured_at", "wall_clock_seconds", "cprofile_overhead_pct_estimate",
}

_REQUIRED_FUNCTION_KEYS = {
    "rank", "qualname", "cumulative_seconds", "cumulative_pct",
    "call_count", "per_call_seconds",
}


def _validate_schema(doc: dict) -> None:
    """Raise AssertionError with a precise message on any schema violation."""
    assert isinstance(doc, dict), f"top-level must be dict, got {type(doc).__name__}"
    assert "metadata" in doc, "missing top-level key 'metadata'"
    assert "top_n_functions" in doc, "missing top-level key 'top_n_functions'"

    md = doc["metadata"]
    assert isinstance(md, dict), "metadata must be dict"
    missing = _REQUIRED_METADATA_KEYS - md.keys()
    assert not missing, f"metadata missing keys: {sorted(missing)}"
    assert md["scale"] == "dev", f"scale must be 'dev', got {md['scale']!r}"
    assert isinstance(md["agents"], int) and md["agents"] > 0
    assert isinstance(md["num_days"], int) and md["num_days"] > 0
    assert isinstance(md["seed"], int)
    assert isinstance(md["wall_clock_seconds"], (int, float))
    assert md["wall_clock_seconds"] > 0

    fns = doc["top_n_functions"]
    assert isinstance(fns, list), "top_n_functions must be list"
    assert len(fns) > 0, "top_n_functions must be non-empty"
    # Sorted descending by cumulative_seconds
    cum = [f["cumulative_seconds"] for f in fns]
    assert cum == sorted(cum, reverse=True), (
        f"top_n_functions must be sorted descending by cumulative_seconds; "
        f"got {cum[:5]} ..."
    )
    # Each entry has all required keys + reasonable types
    for i, fn in enumerate(fns):
        missing = _REQUIRED_FUNCTION_KEYS - fn.keys()
        assert not missing, f"function[{i}] missing keys: {sorted(missing)}"
        assert fn["rank"] == i + 1, f"function[{i}].rank must be {i+1}, got {fn['rank']}"
        assert isinstance(fn["qualname"], str) and fn["qualname"]
        assert 0.0 < fn["cumulative_pct"] <= 100.0, (
            f"function[{i}].cumulative_pct out of (0, 100]: {fn['cumulative_pct']}"
        )
        assert isinstance(fn["call_count"], int) and fn["call_count"] > 0


# ---- Tests ------------------------------------------------------------------


class TestSchemaHandcrafted:
    """A hand-crafted JSON literal must validate cleanly."""

    def test_schema_validates_handcrafted_minimal(self) -> None:
        doc = {
            "metadata": {
                "scale": "dev",
                "agents": 100,
                "num_days": 1,
                "seed": 42,
                "python_version": "3.11.0",
                "captured_at": "2026-05-19T12:00:00",
                "wall_clock_seconds": 12.34,
                "cprofile_overhead_pct_estimate": 18.5,
            },
            "top_n_functions": [
                {
                    "rank": 1,
                    "qualname": "synthetic_socio_wind_tunnel.foo:bar",
                    "cumulative_seconds": 5.0,
                    "cumulative_pct": 40.5,
                    "call_count": 1000,
                    "per_call_seconds": 0.005,
                },
                {
                    "rank": 2,
                    "qualname": "synthetic_socio_wind_tunnel.baz:qux",
                    "cumulative_seconds": 3.0,
                    "cumulative_pct": 24.3,
                    "call_count": 500,
                    "per_call_seconds": 0.006,
                },
            ],
        }
        _validate_schema(doc)  # must not raise

    def test_schema_rejects_unsorted(self) -> None:
        doc = {
            "metadata": {
                "scale": "dev", "agents": 100, "num_days": 1, "seed": 42,
                "python_version": "3.11.0", "captured_at": "2026-05-19T12:00:00",
                "wall_clock_seconds": 1.0, "cprofile_overhead_pct_estimate": 0.0,
            },
            "top_n_functions": [
                {"rank": 1, "qualname": "a:b", "cumulative_seconds": 1.0,
                 "cumulative_pct": 10.0, "call_count": 1, "per_call_seconds": 1.0},
                # second is LARGER than first → must reject
                {"rank": 2, "qualname": "c:d", "cumulative_seconds": 5.0,
                 "cumulative_pct": 50.0, "call_count": 1, "per_call_seconds": 5.0},
            ],
        }
        with pytest.raises(AssertionError, match="sorted descending"):
            _validate_schema(doc)


class TestFixturePresent:
    """The git-tracked baseline fixture must exist after this change lands."""

    def test_fixture_file_exists(self) -> None:
        assert FIXTURE_PATH.exists(), (
            f"baseline fixture not found at {FIXTURE_PATH.relative_to(REPO_ROOT)}; "
            f"run `python tools/profile_publishable_smoke.py "
            f"--output tests/fixtures/hot_path_profile_baseline.json` to "
            f"regenerate."
        )

    def test_fixture_parses_as_json(self) -> None:
        if not FIXTURE_PATH.exists():
            pytest.fail(f"fixture missing: {FIXTURE_PATH}")
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
        assert isinstance(doc, dict)

    def test_fixture_satisfies_schema(self) -> None:
        if not FIXTURE_PATH.exists():
            pytest.fail(f"fixture missing: {FIXTURE_PATH}")
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
        _validate_schema(doc)
        # Spec also requires:
        assert doc["metadata"]["scale"] == "dev"
        assert doc["metadata"]["agents"] == 100
        # Fixture file size budget (< 100 KB per spec)
        assert FIXTURE_PATH.stat().st_size < 100 * 1024, (
            f"fixture exceeds 100 KB budget: "
            f"{FIXTURE_PATH.stat().st_size} bytes"
        )
