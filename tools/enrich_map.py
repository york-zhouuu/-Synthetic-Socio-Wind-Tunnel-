#!/usr/bin/env python3
"""
Merge OSM + Overture into a single enriched GeoJSON for Atlas import.

Run after `tools/fetch_overture.py`:

    python3 tools/enrich_map.py

Reads:
    data/lanecove_osm.geojson
    data/overture_buildings.geojson
    data/overture_places.geojson

Writes:
    data/lanecove_enriched.geojson
    data/lanecove_enriched.stats.json   (MergeStats counters)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from synthetic_socio_wind_tunnel.cartography.conflation import (
    merge_sources,
    write_feature_collection,
)

_DATA = _REPO_ROOT / "data"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--osm", default=str(_DATA / "lanecove_osm.geojson"))
    ap.add_argument("--buildings", default=str(_DATA / "overture_buildings.geojson"))
    ap.add_argument("--places", default=str(_DATA / "overture_places.geojson"))
    ap.add_argument("--out", default=str(_DATA / "lanecove_enriched.geojson"))
    ap.add_argument("--place-confidence", type=float, default=0.5,
                    help="Drop Places below this confidence when no polygon host is found")
    ap.add_argument("--stub-size-m", type=float, default=8.0,
                    help="Edge of synthetic square polygon for un-hosted Places")
    args = ap.parse_args()

    def _opt(path: str) -> str | None:
        return path if Path(path).exists() else None

    osm_path = _opt(args.osm)
    if osm_path is None:
        print(f"Error: OSM input not found: {args.osm}", file=sys.stderr)
        return 2

    fc, stats = merge_sources(
        osm_path,
        _opt(args.buildings),
        _opt(args.places),
        place_confidence_floor=args.place_confidence,
        stub_size_m=args.stub_size_m,
    )

    write_feature_collection(fc, args.out)
    stats_path = Path(args.out).with_suffix(".stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats.as_dict(), f, indent=2, ensure_ascii=False)

    print(f"Wrote {args.out} ({len(fc['features'])} features)")
    print(f"Wrote {stats_path}")
    print(json.dumps(stats.as_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
