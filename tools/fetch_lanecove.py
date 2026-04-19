#!/usr/bin/env python3
"""
Fetch OpenStreetMap data for Lane Cove, NSW 2066, Australia via Overpass API.

Outputs GeoJSON to data/lanecove_osm.geojson.
"""

import json
import os
import sys
import time
from pathlib import Path
from collections import defaultdict

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data"
OUTPUT_FILE = OUTPUT_DIR / "lanecove_osm.geojson"

# Lane Cove 2066 bounding box: S, W, N, E
# Covers: Lane Cove, Lane Cove West, Linley Point, Longueville
# North: M2 / Lane Cove Tunnel
# East:  Pacific Highway
# South: Longueville / River Rd
# West:  Lane Cove River
BBOX = (-33.843, 151.145, -33.798, 151.178)


def build_query_area(area_filter: str) -> str:
    """Build an Overpass QL query using an area filter."""
    return f"""
[out:json][timeout:60];
{area_filter}
(
  way["building"](area.searchArea);
  way["highway"](area.searchArea);
  way["leisure"](area.searchArea);
  node["amenity"](area.searchArea);
  node["shop"](area.searchArea);
);
out body;
>;
out skel qt;
"""


def build_query_bbox() -> str:
    """Build an Overpass QL query using bounding box."""
    s, w, n, e = BBOX
    bbox = f"{s},{w},{n},{e}"
    return f"""
[out:json][timeout:120];
(
  way["building"]({bbox});
  way["highway"]({bbox});
  way["leisure"]({bbox});
  way["landuse"]({bbox});
  way["natural"="water"]({bbox});
  way["natural"="coastline"]({bbox});
  way["waterway"]({bbox});
  relation["natural"="water"]({bbox});
  node["amenity"]({bbox});
  node["shop"]({bbox});
);
out body;
>;
out skel qt;
"""


AREA_STRATEGIES = [
    ('area["name"="Lane Cove"]["admin_level"="10"]->.searchArea;', "admin_level=10"),
    ('area["name"="Lane Cove"]["boundary"="administrative"]->.searchArea;', "boundary=administrative"),
    ('area["postal_code"="2066"]->.searchArea;', "postal_code=2066"),
]


def query_overpass(query: str) -> dict | None:
    """Send a query to Overpass API and return parsed JSON, or None on failure."""
    print(f"  Sending query ({len(query)} chars)...")
    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        n_elements = len(data.get("elements", []))
        print(f"  Received {n_elements} elements.")
        return data if n_elements > 0 else None
    except requests.RequestException as exc:
        print(f"  Request failed: {exc}")
        return None


def fetch_osm_data() -> dict:
    """Use bounding box to fetch full 2066 area. Return Overpass JSON."""
    print("Strategy: bounding box (full Lane Cove 2066 + LGA)")
    query = build_query_bbox()
    data = query_overpass(query)
    if data:
        return data

    # Fallback: try area strategies
    for area_filter, label in AREA_STRATEGIES:
        print(f"Fallback strategy: {label}")
        query = build_query_area(area_filter)
        data = query_overpass(query)
        if data:
            return data
        print("  No results, trying next strategy...")
        time.sleep(2)

    print("ERROR: All strategies failed.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Overpass JSON -> GeoJSON conversion
# ---------------------------------------------------------------------------

def overpass_to_geojson(data: dict) -> dict:
    """Convert Overpass JSON to GeoJSON FeatureCollection.

    - Nodes with tags become Point features.
    - Ways with tags become LineString or Polygon features
      (closed ways with building/leisure tags become Polygons).
    - Bare nodes (no tags, used only as way references) are skipped.
    """
    elements = data.get("elements", [])

    # Build node index: id -> (lon, lat)
    node_index: dict[int, tuple[float, float]] = {}
    way_index: dict[int, dict] = {}
    for el in elements:
        if el["type"] == "node":
            node_index[el["id"]] = (el.get("lon", 0.0), el.get("lat", 0.0))
        elif el["type"] == "way":
            way_index[el["id"]] = el

    features = []
    stats: dict[str, int] = defaultdict(int)

    for el in elements:
        tags = el.get("tags", {})

        if el["type"] == "node" and tags:
            # Tagged node -> Point
            coords = [el.get("lon", 0.0), el.get("lat", 0.0)]
            cat = _categorize(tags)
            stats[cat] += 1
            features.append({
                "type": "Feature",
                "id": f"node/{el['id']}",
                "properties": {**tags, "_osm_type": "node", "_osm_id": el["id"], "_category": cat},
                "geometry": {"type": "Point", "coordinates": coords},
            })

        elif el["type"] == "way" and tags:
            nds = el.get("nodes", [])
            coords = [list(node_index[n]) for n in nds if n in node_index]
            if len(coords) < 2:
                continue

            cat = _categorize(tags)
            stats[cat] += 1

            # Determine geometry type
            is_closed = len(coords) >= 4 and coords[0] == coords[-1]
            is_area = "building" in tags or "leisure" in tags or "landuse" in tags or tags.get("natural") == "water"
            if is_closed and is_area:
                geom = {"type": "Polygon", "coordinates": [coords]}
            else:
                geom = {"type": "LineString", "coordinates": coords}

            features.append({
                "type": "Feature",
                "id": f"way/{el['id']}",
                "properties": {**tags, "_osm_type": "way", "_osm_id": el["id"], "_category": cat},
                "geometry": geom,
            })

        elif el["type"] == "relation" and tags:
            # Handle multipolygon relations (water bodies, etc.)
            cat = _categorize(tags)
            members = el.get("members", [])
            outer_ways = [m for m in members if m.get("role") == "outer" and m.get("type") == "way"]
            for ow in outer_ways:
                way_id = ow["ref"]
                # Find this way in elements
                way_el = way_index.get(way_id)
                if not way_el:
                    continue
                nds = way_el.get("nodes", [])
                coords = [list(node_index[n]) for n in nds if n in node_index]
                if len(coords) < 3:
                    continue
                is_closed = len(coords) >= 4 and coords[0] == coords[-1]
                if is_closed:
                    geom = {"type": "Polygon", "coordinates": [coords]}
                else:
                    geom = {"type": "LineString", "coordinates": coords}
                stats[cat] += 1
                features.append({
                    "type": "Feature",
                    "id": f"relation/{el['id']}/way/{way_id}",
                    "properties": {**tags, "_osm_type": "relation", "_osm_id": el["id"], "_category": cat},
                    "geometry": geom,
                })

    return features, stats


def _categorize(tags: dict) -> str:
    if "building" in tags:
        return "building"
    if "highway" in tags:
        return "highway"
    if tags.get("natural") in ("water", "coastline") or "waterway" in tags:
        return "water"
    if "leisure" in tags:
        return "leisure"
    if "landuse" in tags:
        return "landuse"
    if "amenity" in tags:
        return "amenity"
    if "shop" in tags:
        return "shop"
    return "other"


def main():
    print("=" * 60)
    print("Fetching OSM data for Lane Cove, NSW 2066")
    print("=" * 60)

    osm_data = fetch_osm_data()

    print("\nConverting to GeoJSON...")
    features, stats = overpass_to_geojson(osm_data)

    geojson = {
        "type": "FeatureCollection",
        "name": "Lane Cove NSW 2066 OSM Extract",
        "features": features,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"\nSaved to: {OUTPUT_FILE}")
    print(f"File size: {size_kb:.1f} KB")
    print(f"Total features: {len(features)}")
    print("\nBreakdown by category:")
    for cat in sorted(stats):
        print(f"  {cat:12s}: {stats[cat]}")
    print("Done.")


if __name__ == "__main__":
    main()
