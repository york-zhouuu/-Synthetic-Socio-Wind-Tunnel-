#!/usr/bin/env python3
"""
Fetch Overture Maps Buildings + Places for Lane Cove, NSW (2066).

Wraps the `overturemaps` CLI (from PyPI) with a stable bbox + output layout
so downstream conflation can replay without arguments.

Install:
    pip install -e ".[map-enrichment]"
    # or: uvx overturemaps ...

Run:
    python3 tools/fetch_overture.py

Writes:
    data/sources/overture_buildings_<YYYY-MM>.geojson
    data/sources/overture_places_<YYYY-MM>.geojson
    data/overture_buildings.geojson   (copy of the latest buildings snapshot)
    data/overture_places.geojson      (copy of the latest places snapshot)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import subprocess
import sys
from pathlib import Path

# (min_lon, min_lat, max_lon, max_lat) — Lane Cove 2066 + light buffer.
LANECOVE_BBOX: tuple[float, float, float, float] = (
    151.145, -33.843, 151.178, -33.798,
)

_REPO = Path(__file__).resolve().parent.parent
_DATA = _REPO / "data"
_SOURCES = _DATA / "sources"


def _bbox_arg(bbox: tuple[float, float, float, float]) -> str:
    return ",".join(f"{v:.6f}" for v in bbox)


def _run_overture_download(
    theme_type: str,
    bbox: tuple[float, float, float, float],
    out_path: Path,
) -> None:
    """Invoke `overturemaps download --type=<theme_type> --bbox=... -f geojson`.

    Falls back to `uvx overturemaps` when the CLI is not directly on PATH.
    """
    cmd_base = ["overturemaps", "download",
                f"--bbox={_bbox_arg(bbox)}",
                f"--type={theme_type}",
                "-f", "geojson",
                "-o", str(out_path)]

    try:
        subprocess.run(cmd_base, check=True)
        return
    except FileNotFoundError:
        pass

    # Fall back to uvx (no local install required)
    subprocess.run(["uvx", *cmd_base], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bbox", type=str, default=None,
                    help="Override bbox as 'min_lon,min_lat,max_lon,max_lat'")
    ap.add_argument("--stamp", type=str, default=None,
                    help="Timestamp suffix for snapshot files (default YYYY-MM)")
    args = ap.parse_args()

    if args.bbox:
        parts = [float(x) for x in args.bbox.split(",")]
        if len(parts) != 4:
            print(f"Error: --bbox needs 4 values, got {args.bbox}", file=sys.stderr)
            return 2
        bbox = (parts[0], parts[1], parts[2], parts[3])
    else:
        bbox = LANECOVE_BBOX

    stamp = args.stamp or _dt.date.today().strftime("%Y-%m")
    _SOURCES.mkdir(parents=True, exist_ok=True)
    _DATA.mkdir(parents=True, exist_ok=True)

    snapshots = {
        "building": _SOURCES / f"overture_buildings_{stamp}.geojson",
        "place":    _SOURCES / f"overture_places_{stamp}.geojson",
    }
    latest = {
        "building": _DATA / "overture_buildings.geojson",
        "place":    _DATA / "overture_places.geojson",
    }

    for theme_type, snap_path in snapshots.items():
        print(f"[fetch_overture] {theme_type}: bbox={_bbox_arg(bbox)} → {snap_path.name}")
        _run_overture_download(theme_type, bbox, snap_path)
        shutil.copyfile(snap_path, latest[theme_type])
        print(f"[fetch_overture]   copied to {latest[theme_type].name}")

    print(f"\nDone. Snapshot stamp: {stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
