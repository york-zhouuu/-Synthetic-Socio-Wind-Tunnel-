"""Publishable run integrity checker.

Scans all `seed_*.json` files in a suite output directory and asserts:
- reproducibility_lock has all 7 fields, with `provider` non-None
- replan_count + replan_no_op_count both present
- Gemini path: cost_breakdown.total > 0 (real-LLM cost recorded)
- Stub path: cost_breakdown.total == 0 OK
- encounter_stats.total > 0
- trajectory_deviation_m and trajectory_deviation_m_all both populated for hp/gd
- Cross-seed median stability: IQR / median ≤ 0.5

Usage:
    python3 tools/check_publishable_integrity.py <suite_dir>
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


REQUIRED_REP_LOCK_FIELDS = {
    "seed_pool", "model_version", "provider", "prompt_template_hash",
    "LANE_COVE_PROFILE_hash", "variants_loaded", "code_commit", "phase_config",
}


class CheckError(Exception):
    pass


_REAL_SEED_RE = __import__("re").compile(r"^seed_\d+\.json$")


def _load_seed_files(suite_dir: Path) -> dict[str, list[dict]]:
    """Load real seed result files (`seed_<N>.json`) grouped by variant.

    2026-05-20 fix-publishable-integrity-glob: filter via regex
    `^seed_\\d+\\.json$` to exclude auxiliary files like
    `seed_<N>_positions.json`, `seed_<N>_tick<T>.snapshot.json`,
    `seed_<N>_day<D>.partial.json`. The previous `glob("seed_*.json")`
    matched all of these, producing ~23 false positive errors per cell.
    """
    by_variant: dict[str, list[dict]] = {}
    for variant_dir in sorted(suite_dir.iterdir()):
        if not variant_dir.is_dir() or not variant_dir.name.startswith("variant_"):
            continue
        seeds: list[dict] = []
        for seed_file in sorted(variant_dir.glob("seed_*.json")):
            if not _REAL_SEED_RE.match(seed_file.name):
                continue  # skip auxiliary files
            with seed_file.open(encoding="utf-8") as fh:
                seeds.append(json.load(fh))
        if seeds:
            by_variant[variant_dir.name] = seeds
    return by_variant


def _check_rep_lock(rec: dict, label: str, errors: list[str]) -> None:
    rl = rec.get("run_metrics", {}).get("extensions", {}).get(
        "reproducibility_lock", {},
    )
    if not isinstance(rl, dict):
        errors.append(f"{label}: reproducibility_lock missing or not dict")
        return
    missing = REQUIRED_REP_LOCK_FIELDS - set(rl.keys())
    if missing:
        errors.append(f"{label}: rep_lock missing fields: {sorted(missing)}")
    if rl.get("provider") is None:
        errors.append(f"{label}: rep_lock.provider is None")
    if rl.get("model_version") in (None, ""):
        errors.append(f"{label}: rep_lock.model_version is empty")


def _check_replan_counters(rec: dict, label: str, errors: list[str]) -> None:
    ext = rec.get("run_metrics", {}).get("extensions", {})
    if "replan_count" not in ext:
        errors.append(f"{label}: extensions.replan_count missing")
    if "replan_no_op_count" not in ext:
        errors.append(f"{label}: extensions.replan_no_op_count missing")


def _check_cost(rec: dict, label: str, errors: list[str]) -> None:
    cb = rec.get("run_metrics", {}).get("cost_breakdown")
    rl = rec.get("run_metrics", {}).get("extensions", {}).get(
        "reproducibility_lock", {},
    )
    provider = (rl or {}).get("provider", "stub")
    if provider in ("gemini", "anthropic"):
        if cb is None or cb.get("total", 0) == 0:
            errors.append(
                f"{label}: provider={provider} but cost_breakdown.total==0; "
                "real-LLM run isn't recording tokens?"
            )


def _check_encounter(rec: dict, label: str, errors: list[str]) -> None:
    es = rec.get("run_metrics", {}).get("encounter_stats", {})
    if es.get("total", 0) <= 0:
        errors.append(f"{label}: encounter_stats.total ≤ 0; sim broken?")


def _check_traj_dev(rec: dict, label: str, errors: list[str]) -> None:
    rm = rec.get("run_metrics", {})
    variant = rm.get("variant_name", "")
    if variant in ("hyperlocal_push", "global_distraction"):
        if rm.get("trajectory_deviation_m") is None:
            errors.append(
                f"{label}: variant={variant} but trajectory_deviation_m is None",
            )
        if rm.get("trajectory_deviation_m_all") is None:
            errors.append(
                f"{label}: variant={variant} but trajectory_deviation_m_all is None",
            )


def _check_cross_seed_stability(seeds: list[dict], label: str, errors: list[str]) -> None:
    if len(seeds) < 3:
        return
    enc_medians = [
        rec.get("run_metrics", {}).get("encounter_stats", {}).get("per_day_median", 0)
        for rec in seeds
    ]
    if not enc_medians or all(v == 0 for v in enc_medians):
        return
    median = statistics.median(enc_medians)
    if median == 0:
        return
    quartiles = statistics.quantiles(enc_medians, n=4)
    iqr = quartiles[2] - quartiles[0]
    if median > 0 and iqr / median > 0.5:
        errors.append(
            f"{label}: cross-seed encounter median IQR={iqr:.1f} / "
            f"median={median:.1f} = {iqr/median:.2f} > 0.5 (unstable)"
        )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suite_dir", type=Path)
    args = p.parse_args()

    if not args.suite_dir.is_dir():
        print(f"error: not a directory: {args.suite_dir}", file=sys.stderr)
        return 2

    by_variant = _load_seed_files(args.suite_dir)
    if not by_variant:
        print(f"error: no variant_*/seed_*.json found in {args.suite_dir}", file=sys.stderr)
        return 2

    errors: list[str] = []
    n_records = 0
    for variant, seeds in by_variant.items():
        for rec in seeds:
            seed_id = rec.get("multi_day_result", {}).get("seed", "?")
            label = f"{variant}/seed={seed_id}"
            n_records += 1
            _check_rep_lock(rec, label, errors)
            _check_replan_counters(rec, label, errors)
            _check_cost(rec, label, errors)
            _check_encounter(rec, label, errors)
            _check_traj_dev(rec, label, errors)
        _check_cross_seed_stability(seeds, variant, errors)

    print(f"=== Integrity check: {n_records} seed records across {len(by_variant)} variants ===")
    if errors:
        print(f"❌ {len(errors)} errors:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("✅ All checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
