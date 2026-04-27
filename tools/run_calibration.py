#!/usr/bin/env python3
"""
run_calibration — assess agent population + behavioral calibration vs ABS data.

Reads:
    data/calibration/abs_census_lanecove_2021.json
    data/calibration/abs_travel_survey_sydney_2021.json
    data/calibration/lanecove_popular_times.json

Writes:
    data/calibration/calibration_report.json

Usage:
    python3 tools/run_calibration.py --mode population
    python3 tools/run_calibration.py --mode behavioral
    python3 tools/run_calibration.py --mode all --seed 42

Behavioral mode requires running a 14d × 1000 agent baseline sim, which is
the expensive part (~minutes). Population mode is fast (~1 second).

If a required calibration JSON is missing, the corresponding section of the
report is marked `state: "missing-data"` rather than failing — this lets
downstream publishable suite reports surface "calibration not run" cleanly
instead of crashing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from synthetic_socio_wind_tunnel.agent import LANE_COVE_PROFILE, sample_population
from synthetic_socio_wind_tunnel.agent.calibration import (
    CalibrationStatus,
    assess_behavioral_calibration,
    assess_population_calibration,
    compute_od_chi_squared,
    compute_popular_times_emd,
    compute_population_distance,
)


_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "calibration"
_ABS_CENSUS = _DATA_DIR / "abs_census_lanecove_2021.json"
_ABS_TRAVEL = _DATA_DIR / "abs_travel_survey_sydney_2021.json"
_POPULAR_TIMES = _DATA_DIR / "lanecove_popular_times.json"
_REPORT_PATH = _DATA_DIR / "calibration_report.json"


def _load_json_or_none(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _missing_data_section(reason: str) -> dict:
    return {
        "state": "missing-data",
        "reason": reason,
        "passed": False,
        "acceptance_level": "failing",
    }


def assess_population(*, seed: int = 42, n: int = 1000) -> dict:
    abs_data = _load_json_or_none(_ABS_CENSUS)
    if abs_data is None:
        return _missing_data_section(
            f"{_ABS_CENSUS.name} not found; download from "
            "https://www.abs.gov.au and place in data/calibration/"
        )

    profile = LANE_COVE_PROFILE.model_copy(update={"size": n})
    samples = sample_population(profile, seed=seed)
    p_values = compute_population_distance(samples, abs_data)
    status: CalibrationStatus = assess_population_calibration(p_values)
    return {
        "state": "evaluated",
        "passed": status.passed,
        "acceptance_level": status.acceptance_level,
        "p_values": p_values,
        "failed_dimensions": status.failed_dimensions,
        "details": status.details,
        "n_samples": n,
        "seed": seed,
    }


def assess_behavioral(*, seed: int = 42) -> dict:
    """
    Behavioral assessment placeholder.

    Full implementation requires running a 14-day baseline sim, recording the
    OD matrix + per-POI hourly visit grid, then comparing to ABS Travel Survey
    + Popular Times. That sim infrastructure is wired in `agent-calibration`
    Section 4.3 + 4.4. For now we surface "missing-data" status cleanly so
    the publishable suite report can disclose what's pending.
    """
    abs_travel = _load_json_or_none(_ABS_TRAVEL)
    popular_times = _load_json_or_none(_POPULAR_TIMES)
    missing = []
    if abs_travel is None:
        missing.append(_ABS_TRAVEL.name)
    if popular_times is None:
        missing.append(_POPULAR_TIMES.name)
    if missing:
        return _missing_data_section(
            f"missing: {', '.join(missing)} — see docs/calibration/01-data-sources.md"
        )

    # Once data is available, implementation will:
    # 1. Run a baseline 14-day sim (1000 agents, scripted_plan only)
    # 2. Aggregate OD matrix from agent first-commute movements
    # 3. Aggregate per-POI hourly visits from move events
    # 4. Compare via compute_od_chi_squared + compute_popular_times_emd
    # 5. Pass to assess_behavioral_calibration
    return {
        "state": "not-implemented",
        "passed": False,
        "acceptance_level": "failing",
        "reason": (
            "behavioral sim assessment not yet implemented; ABS data + Popular "
            "Times are present but compute pipeline pending (agent-calibration "
            "Section 4.3-4.4)"
        ),
    }


def write_report(payload: dict) -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return _REPORT_PATH


def _print_summary(payload: dict) -> None:
    pop = payload.get("population", {})
    beh = payload.get("behavioral", {})
    print()
    print("=== calibration summary ===")
    print(f"  population: {pop.get('acceptance_level', '?'):12} "
          f"(state={pop.get('state', '?')})")
    if pop.get("p_values"):
        for dim, p in pop["p_values"].items():
            mark = "✓" if p > 0.10 else "✗"
            print(f"    {mark} {dim:18} p = {p:.4f}")
    print(f"  behavioral: {beh.get('acceptance_level', '?'):12} "
          f"(state={beh.get('state', '?')})")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", choices=["population", "behavioral", "all"],
                    default="all")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n-samples", type=int, default=1000)
    args = ap.parse_args()

    payload: dict[str, Any] = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "seed": args.seed,
    }
    if args.mode in ("population", "all"):
        payload["population"] = assess_population(seed=args.seed, n=args.n_samples)
    if args.mode in ("behavioral", "all"):
        payload["behavioral"] = assess_behavioral(seed=args.seed)

    out = write_report(payload)
    _print_summary(payload)
    print(f"[report] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
