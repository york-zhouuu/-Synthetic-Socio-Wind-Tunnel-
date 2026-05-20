#!/usr/bin/env python3
"""audit_resume_strategies — recommend per-cell --resume-strategy for resume.

Background: `--resume-strategy` (CLAUDE.md tick-level-resume invariant) has
4 modes — `auto` (snapshot→partial fallback), `snapshot-only` (strict),
`partial-only` (legacy), `none` (from scratch). The right value depends
on which artifacts physically exist in the cell directory.

Special case (2026-05-19 D2 attempt 6 fallout, cell-specific):
`sigusr1-graceful-stop-corruption` deleted some cells' per-day partials
via SIGUSR1 misfire + cleanup_partials. Those cells SHALL run with
`--resume-strategy=snapshot-only` because their partial fallback path
is broken (`auto` would silently re-run from day 0 if snapshot ever
fails to load).

This tool scans cells and emits per-cell recommendation:

    DONE             seed_N.json present, real (not quarantined) → skip
    snapshot-only    snapshot present, no partials → forced snapshot
    auto             snapshot + partials both present → default safe
    partial-only     partials only, no snapshot → legacy path
    none             nothing → must restart from day 0

Usage:
    python tools/audit_resume_strategies.py \\
        data/experiments/20260518_..._seed42_... 42 \\
        data/experiments/20260518_..._seed43_... 43

    python tools/audit_resume_strategies.py <suite_dir> <seed> --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


VARIANTS = (
    "baseline", "global_distraction", "hyperlocal_push", "phone_friction",
)


def _scan_cell(suite_dir: Path, seed: int, variant: str) -> dict[str, Any]:
    """Inspect a single cell and return its state + resume recommendation."""
    vdir = suite_dir / f"variant_{variant}"
    if not vdir.is_dir():
        return {
            "suite": suite_dir.name, "seed": seed, "variant": variant,
            "state": "MISSING_DIR",
            "recommended_strategy": "none",
            "note": "variant directory does not exist",
        }

    # Real seed_N.json = DONE (quarantined ones have suffix .gracefulstop_stub_*)
    real_seed_json = vdir / f"seed_{seed}.json"
    if real_seed_json.is_file():
        return {
            "suite": suite_dir.name, "seed": seed, "variant": variant,
            "state": "DONE",
            "recommended_strategy": "skip",
            "note": "seed_N.json present — cell complete",
        }

    # 2026-05-21 NEW-B (audit-tools-pid-prefix-recognition):
    # also match PID-prefixed format `seed_<N>_pid<PID>_tick<T>.snapshot.json`
    # introduced by R1 (fix-snapshot-filename-spawn-collision).
    import re as _re_audit
    snapshot_pattern = _re_audit.compile(
        rf"^seed_{seed}(?:_pid\d+)?_tick(?P<tick>_final|\d+)\.snapshot\.json$"
    )
    snapshots: list[Path] = []
    for p in vdir.glob(f"seed_{seed}_*.snapshot.json"):
        if snapshot_pattern.match(p.name):
            snapshots.append(p)
    snapshots.sort()
    partials = sorted(vdir.glob(f"seed_{seed}_day*.partial.json"))
    wal = vdir / f"seed_{seed}.wal.jsonl"
    # Quarantined stub files include any *.gracefulstop_stub_* in the
    # cell dir — not just seed_N.* (also aggregate.json,
    # seed_N_positions.json, etc.)
    quarantined = list(vdir.glob("*.gracefulstop_stub_*"))

    # Extract numeric tick from each snapshot. tick_final entries
    # are tracked separately (their authority comes from mtime, not
    # numeric ordering).
    snapshot_ticks: list[int] = []
    tick_final_count = 0
    for s in snapshots:
        m = snapshot_pattern.match(s.name)
        if not m:
            continue
        tick_str = m.group("tick")
        if tick_str == "_final":
            tick_final_count += 1
            continue
        try:
            snapshot_ticks.append(int(tick_str))
        except ValueError:
            pass

    partial_days: list[int] = []
    for p in partials:
        try:
            tail = p.stem.rsplit("_day", 1)[-1].split(".")[0]
            partial_days.append(int(tail))
        except (ValueError, IndexError):
            pass

    has_snapshot = bool(snapshot_ticks) or tick_final_count > 0
    has_partial = bool(partial_days)
    has_wal = wal.is_file()

    # Decision tree
    if has_snapshot and has_partial:
        state = "INTERRUPTED"
        strategy = "auto"
        note = "snapshot + partials both present — auto safe"
    elif has_snapshot and not has_partial:
        state = "INTERRUPTED_PARTIAL_MISSING"
        strategy = "snapshot-only"
        if quarantined:
            note = (
                "snapshot only — partials were deleted "
                "(quarantined stub files indicate prior "
                "sigusr1-graceful-stop-corruption); "
                "auto would silently fall back to day 0 on snapshot "
                "read failure → force snapshot-only"
            )
        else:
            note = (
                "snapshot only, no partials — recommend snapshot-only "
                "to fail loudly if snapshot is unreadable rather than "
                "silently restart from day 0"
            )
    elif has_partial and not has_snapshot:
        state = "INTERRUPTED_SNAPSHOT_MISSING"
        strategy = "partial-only"
        note = "partials only — legacy path"
    elif has_wal and not has_snapshot and not has_partial:
        state = "WAL_ONLY"
        strategy = "none"
        note = (
            "only WAL — likely setup-phase crash before any partial "
            "or snapshot was written; from-scratch run"
        )
    else:
        state = "NEVER_STARTED"
        strategy = "none"
        note = "no artifacts found"

    return {
        "suite": suite_dir.name, "seed": seed, "variant": variant,
        "state": state,
        "recommended_strategy": strategy,
        "note": note,
        "snapshot_ticks": snapshot_ticks,
        "latest_snapshot_tick": (
            max(snapshot_ticks) if snapshot_ticks else None
        ),
        "partial_days": partial_days,
        "latest_partial_day": (
            max(partial_days) if partial_days else None
        ),
        "has_wal": has_wal,
        "quarantined_stub_count": len(quarantined),
    }


def _print_table(rows: list[dict[str, Any]]) -> None:
    """Compact human-readable table for terminal."""
    print(f"{'seed':>4} {'variant':<20} {'state':<32} "
          f"{'strategy':<14} {'snap':<6} {'day':<5} note")
    print("-" * 110)
    for r in rows:
        snap = (str(r.get("latest_snapshot_tick")) if r.get("latest_snapshot_tick") is not None else "-")
        day = (str(r.get("latest_partial_day")) if r.get("latest_partial_day") is not None else "-")
        print(
            f"{r['seed']:>4} {r['variant']:<20} {r['state']:<32} "
            f"{r['recommended_strategy']:<14} {snap:<6} {day:<5} "
            f"{r['note'][:60]}",
        )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "args", nargs="+",
        help="Alternating <suite_dir> <seed> pairs",
    )
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of table")
    p.add_argument("--variants", default=",".join(VARIANTS),
                   help=f"Comma-separated variants (default: {','.join(VARIANTS)})")
    args = p.parse_args()

    if len(args.args) % 2 != 0:
        print("ERROR: args must come in (suite_dir, seed) pairs",
              file=sys.stderr)
        return 2

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    rows: list[dict[str, Any]] = []
    incomplete = 0
    needs_snapshot_only = 0

    for i in range(0, len(args.args), 2):
        suite_dir = Path(args.args[i])
        try:
            seed = int(args.args[i + 1])
        except ValueError:
            print(f"ERROR: '{args.args[i+1]}' is not a seed number",
                  file=sys.stderr)
            return 2

        if not suite_dir.exists():
            print(f"ERROR: suite_dir not found: {suite_dir}", file=sys.stderr)
            return 2

        for variant in variants:
            row = _scan_cell(suite_dir, seed, variant)
            rows.append(row)
            if row["recommended_strategy"] != "skip":
                incomplete += 1
            if row["recommended_strategy"] == "snapshot-only":
                needs_snapshot_only += 1

    if args.json:
        print(json.dumps({
            "cells": rows,
            "incomplete_cells": incomplete,
            "needs_snapshot_only": needs_snapshot_only,
        }, indent=2, ensure_ascii=False))
    else:
        _print_table(rows)
        print()
        print(f"summary: incomplete={incomplete}  "
              f"needs_snapshot_only={needs_snapshot_only}  "
              f"total_cells={len(rows)}")

    return 0 if incomplete == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
