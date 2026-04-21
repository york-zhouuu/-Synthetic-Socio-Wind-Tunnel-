#!/usr/bin/env python3
"""
Run the Phase 1.5 fitness audit on an atlas and produce a structured report.

Usage:
    python3 tools/run_fitness_audit.py
    python3 tools/run_fitness_audit.py --scale full
    python3 tools/run_fitness_audit.py --category e1-digital-lure --verbose
    python3 tools/run_fitness_audit.py --output path/to/report.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from synthetic_socio_wind_tunnel.fitness import run_audit
from synthetic_socio_wind_tunnel.fitness.report import AuditStatus


_DEFAULT_ATLAS = "data/lanecove_atlas.json"
_DEFAULT_OUTPUT = "data/fitness-report.json"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Phase 1.5 fitness audit (see openspec/changes/realign-to-social-thesis)"
    )
    p.add_argument(
        "--atlas",
        default=_DEFAULT_ATLAS,
        help=f"Path to atlas JSON (default: {_DEFAULT_ATLAS})",
    )
    p.add_argument(
        "--scale",
        choices=("quick", "full"),
        default="quick",
        help="quick = 100×72, full = 1000×288 (slower). Default: quick",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Alias for --scale full",
    )
    p.add_argument(
        "--category",
        action="append",
        dest="categories",
        help="Run only the named category. Repeatable. Default: all.",
    )
    p.add_argument(
        "--output",
        default=_DEFAULT_OUTPUT,
        help=f"Output JSON path (default: {_DEFAULT_OUTPUT}). "
             "Pass '-' to skip writing.",
    )
    p.add_argument(
        "--profile-seed",
        type=int,
        default=42,
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
    )
    return p.parse_args()


def _print_report(report, verbose: bool) -> None:
    print(f"atlas:     {report.atlas_source}")
    print(f"signature: {report.atlas_signature[:16]}…")
    print(f"generated: {report.generated_at.isoformat()}")
    print()
    for cat in report.categories:
        print(f"[{cat.category}]")
        for r in cat.results:
            status = r.status.value.upper()
            line = f"  {status:5}  {r.id}"
            if verbose and r.detail:
                line += f"  —  {r.detail}"
            print(line)
            if r.status != AuditStatus.PASS and r.mitigation_change:
                print(f"         ↳ mitigation: {r.mitigation_change}")
        print()
    if report.site_fitness:
        sf = report.site_fitness
        print("[site_fitness]")
        print(f"  named_building_ratio:  {sf.named_building_ratio:.2%}")
        print(f"  residential_ratio:     {sf.residential_ratio:.2%}")
        print(f"  density:               {sf.density_buildings_per_km2:.0f} buildings/km²")
        for note in sf.notes:
            print(f"  • {note}")
        print()
    if report.scale_baseline:
        sb = report.scale_baseline
        print("[scale_baseline]")
        print(f"  {sb.agents} agents × {sb.ticks} ticks")
        print(f"  total: {sb.wall_seconds_total:.2f}s  "
              f"p50: {sb.wall_seconds_p50 * 1000:.1f}ms  "
              f"p99: {sb.wall_seconds_p99 * 1000:.1f}ms")
        print()
    if report.cost_baseline:
        cb = report.cost_baseline
        print("[cost_baseline]")
        print(f"  sonnet calls (est): {cb.sonnet_calls_estimated}")
        print(f"  haiku calls (est):  {cb.haiku_calls_estimated}")
        print(f"  daily USD range:    ${cb.total_usd_lower:.2f} – ${cb.total_usd_upper:.2f}")


def main() -> int:
    args = _parse_args()

    atlas_path = Path(args.atlas)
    if not atlas_path.exists():
        print(f"ERROR: atlas not found at {atlas_path}", file=sys.stderr)
        print("Hint: run `make enrich-map` first, or pass --atlas <path>.", file=sys.stderr)
        return 2

    scale = "full" if args.full else args.scale
    categories = tuple(args.categories) if args.categories else None
    output = None if args.output == "-" else Path(args.output)

    report = run_audit(
        atlas_path,
        scale=scale,
        output_path=output,
        profile_seed=args.profile_seed,
        categories=categories,
    )

    _print_report(report, verbose=args.verbose)

    if output is not None:
        print(f"→ written: {output}")

    # Exit semantics: FAILs are data (Phase 2 gaps are expected FAILs).
    # The CLI exits 0 on any successful run. A caller wanting to gate on
    # specific audit outcomes should read the JSON and decide there.
    return 0


if __name__ == "__main__":
    sys.exit(main())
