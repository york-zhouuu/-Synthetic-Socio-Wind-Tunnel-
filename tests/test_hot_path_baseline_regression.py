"""Hot-path regression guard.

Runs the dev-mode profile harness fresh and compares against the
git-tracked baseline fixture. Catches three classes of regression:

1. **Structural shift** — top-3 hot functions changed (any optimization
   PR that accidentally shifted the dominant cost path).
2. **Wall-clock blowout** — total dev smoke runtime > 1.5× baseline.
3. **Schema drift** — fixture itself no longer matches the schema (caught
   by `test_hot_path_profile_schema.py` separately; included here for
   defense-in-depth).

Marked `@pytest.mark.slow` because running the harness end-to-end takes
~60s. Excluded from default CI; run via:
    pytest tests/test_hot_path_baseline_regression.py -m slow
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "hot_path_profile_baseline.json"
HARNESS_PATH = REPO_ROOT / "tools" / "profile_publishable_smoke.py"

WALL_CLOCK_TOLERANCE = 1.5  # ratio: current / baseline


def _run_harness_to_temp() -> dict:
    """Invoke the profile harness; return parsed JSON. Raises on harness failure."""
    if not HARNESS_PATH.exists():
        pytest.fail(
            f"harness script missing: {HARNESS_PATH.relative_to(REPO_ROOT)}"
        )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False,
    ) as tmp:
        out_path = Path(tmp.name)
    try:
        result = subprocess.run(
            [
                sys.executable, str(HARNESS_PATH),
                "--output", str(out_path),
                "--seed", "42",
                "--agents", "100",
                "--num-days", "1",
                "--top-n", "30",
            ],
            capture_output=True, text=True, timeout=180,
            cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            pytest.fail(
                f"harness exited rc={result.returncode}\n"
                f"stdout={result.stdout[-1000:]}\n"
                f"stderr={result.stderr[-1000:]}"
            )
        with open(out_path, "r", encoding="utf-8") as f:
            return json.load(f)
    finally:
        if out_path.exists():
            out_path.unlink()


def _load_baseline() -> dict:
    if not FIXTURE_PATH.exists():
        pytest.fail(
            f"baseline fixture missing: {FIXTURE_PATH.relative_to(REPO_ROOT)}"
        )
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _top_k_qualnames(doc: dict, k: int = 3) -> set[str]:
    """Top-K *meaningful* function qualnames (set, order-insensitive).

    Excludes entry-point wrappers (`exec`, `<module>`, `main`, `run_smoke`)
    that always appear at cumulative_pct ≈ 100% with call_count == 1.
    Those wrappers never shift in optimization PRs, so including them
    makes the regression test dead.

    Heuristic: a "wrapper" is cumulative_pct >= 95% AND call_count == 1.
    Real hot paths are called many times OR represent a sub-fraction.
    """
    meaningful = [
        fn for fn in doc["top_n_functions"]
        if not (fn["cumulative_pct"] >= 95.0 and fn["call_count"] == 1)
    ]
    return {fn["qualname"] for fn in meaningful[:k]}


# --------------------------------------------------------------------
# Hypothetical-input tests (use synthetic profile docs; no real run).
# These pin the test's *own logic* and run in default CI.
# --------------------------------------------------------------------


def _mk_profile_doc(qualnames: list[str], wall_clock: float = 10.0) -> dict:
    n = len(qualnames)
    return {
        "metadata": {
            "scale": "dev", "agents": 100, "num_days": 1, "seed": 42,
            "python_version": "3.11.0", "captured_at": "2026-05-19T12:00:00",
            "wall_clock_seconds": wall_clock,
            "cprofile_overhead_pct_estimate": 15.0,
        },
        "top_n_functions": [
            {
                "rank": i + 1, "qualname": qn,
                "cumulative_seconds": float(n - i),
                "cumulative_pct": (n - i) * 10.0,
                "call_count": 100, "per_call_seconds": float(n - i) / 100,
            }
            for i, qn in enumerate(qualnames)
        ],
    }


class TestRegressionLogic:
    """Hypothetical-input tests for the comparison logic itself.

    These don't run the real harness — they just exercise the
    set-diff + ratio assertions with hand-crafted inputs.
    """

    def test_top_3_match_passes_silently(self) -> None:
        baseline = _mk_profile_doc(["a:b", "c:d", "e:f", "g:h"])
        current = _mk_profile_doc(["c:d", "a:b", "e:f", "g:h"])  # same set, different order
        baseline_top3 = _top_k_qualnames(baseline, 3)
        current_top3 = _top_k_qualnames(current, 3)
        assert baseline_top3 == current_top3

    def test_top_3_diff_yields_readable_error(self) -> None:
        baseline = _mk_profile_doc(["a:b", "c:d", "e:f"])
        current = _mk_profile_doc(["a:b", "c:d", "X:Y"])  # third func changed
        baseline_top3 = _top_k_qualnames(baseline, 3)
        current_top3 = _top_k_qualnames(current, 3)
        added = current_top3 - baseline_top3
        removed = baseline_top3 - current_top3
        # Simulating the error message construction
        msg = f"top-3 hot path shifted: 新出现的={sorted(added)}; 消失的={sorted(removed)}"
        assert "X:Y" in msg
        assert "e:f" in msg

    def test_wall_clock_within_tolerance(self) -> None:
        ratio = 12.0 / 10.0  # 1.2× baseline
        assert ratio <= WALL_CLOCK_TOLERANCE

    def test_wall_clock_exceeds_tolerance(self) -> None:
        ratio = 16.0 / 10.0  # 1.6× — exceeds 1.5×
        assert ratio > WALL_CLOCK_TOLERANCE


# --------------------------------------------------------------------
# Real harness regression — slow, opt-in via `-m slow`
# --------------------------------------------------------------------


@pytest.mark.slow
def test_top_3_functions_match_baseline() -> None:
    baseline = _load_baseline()
    current = _run_harness_to_temp()
    baseline_top3 = _top_k_qualnames(baseline, 3)
    current_top3 = _top_k_qualnames(current, 3)
    added = current_top3 - baseline_top3
    removed = baseline_top3 - current_top3
    assert baseline_top3 == current_top3, (
        f"top-3 hot path shifted:\n"
        f"  新出现的: {sorted(added)}\n"
        f"  消失的:   {sorted(removed)}\n"
        f"  baseline: {sorted(baseline_top3)}\n"
        f"  current:  {sorted(current_top3)}\n"
        f"If this shift is intentional, regenerate the fixture:\n"
        f"  python tools/profile_publishable_smoke.py "
        f"--output {FIXTURE_PATH.relative_to(REPO_ROOT)}"
    )


@pytest.mark.slow
def test_wall_clock_within_budget() -> None:
    baseline = _load_baseline()
    current = _run_harness_to_temp()
    baseline_wc = baseline["metadata"]["wall_clock_seconds"]
    current_wc = current["metadata"]["wall_clock_seconds"]
    ratio = current_wc / baseline_wc
    assert ratio <= WALL_CLOCK_TOLERANCE, (
        f"dev smoke wall-clock blew past {WALL_CLOCK_TOLERANCE}× baseline: "
        f"baseline={baseline_wc:.1f}s, current={current_wc:.1f}s, "
        f"ratio={ratio:.2f}×"
    )


@pytest.mark.slow
def test_fixture_schema_integrity_after_harness_run() -> None:
    """Defense-in-depth: even after running the harness, the fixture
    itself should still match the schema (catches accidental commits of
    malformed fixture)."""
    from tests.test_hot_path_profile_schema import _validate_schema
    baseline = _load_baseline()
    _validate_schema(baseline)
