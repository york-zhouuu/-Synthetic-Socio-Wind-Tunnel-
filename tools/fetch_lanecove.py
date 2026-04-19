#!/usr/bin/env python3
"""
Fetch Lane Cove (NSW 2066) OSM data via separate Overpass queries
to avoid timeout issues with a single large query.
"""

import json
import time
import requests
from collections import defaultdict

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
REQUEST_TIMEOUT = 200  # seconds
QUERY_DELAY = 5  # seconds between queries
MAX_RETRIES = 3

# Lane Cove 2066 bounding box
BBOX = "-33.843,151.145,-33.798,151.178"
# Larger bbox for water features (Lane Cove River)
WATER_BBOX = "-33.855,151.130,-33.790,151.190"

POLYGON_TAGS = {"building", "leisure", "landuse", "water", "natural"}


def overpass_query(query_text: str, label: str) -> dict:
    """Run an Overpass query with retry logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"  [{label}] Sending query (attempt {attempt}/{MAX_RETRIES})...")
        try:
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query_text},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 429:
                wait = 15 * attempt
                print(f"  [{label}] Rate limited (429). Waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 504:
                wait = 10 * attempt
                print(f"  [{label}] Gateway timeout (504). Waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            elements = data.get("elements", [])
            print(f"  [{label}] Got {len(elements)} elements")
            return data
        except requests.exceptions.ReadTimeout:
            wait = 10 * attempt
            print(f"  [{label}] Read timeout. Waiting {wait}s...")
            time.sleep(wait)
            continue
    raise RuntimeError(f"[{label}] Failed after {MAX_RETRIES} attempts")


def build_queries():
    """Return list of (label, query_string) tuples."""
    queries = []

    # 1. Buildings
    queries.append(("buildings", f"""
[out:json][timeout:90];
(
  way["building"]({BBOX});
);
out body;
>;
out skel qt;
"""))

    # 2. Highways
    queries.append(("highways", f"""
[out:json][timeout:90];
(
  way["highway"]({BBOX});
);
out body;
>;
out skel qt;
"""))

    # 3. Leisure + Landuse
    queries.append(("leisure_landuse", f"""
[out:json][timeout:90];
(
  way["leisure"]({BBOX});
  way["landuse"]({BBOX});
);
out body;
>;
out skel qt;
"""))

    # 4a. Water ways (larger bbox for river)
    queries.append(("water_ways", f"""
[out:json][timeout:180];
(
  way["natural"="water"]({WATER_BBOX});
  way["waterway"]({WATER_BBOX});
);
out body;
>;
out skel qt;
"""))

    # 4b. Water relations (larger bbox for river)
    queries.append(("water_relations", f"""
[out:json][timeout:180];
(
  relation["natural"="water"]({WATER_BBOX});
);
out body;
>;
out skel qt;
"""))

    # 5. Amenities + Shops (nodes)
    queries.append(("amenities_shops", f"""
[out:json][timeout:90];
(
  node["amenity"]({BBOX});
  node["shop"]({BBOX});
);
out body;
"""))

    return queries


def categorize(tags: dict) -> str:
    """Determine the category string from OSM tags."""
    if "building" in tags:
        return "building"
    if tags.get("natural") == "water" or "waterway" in tags:
        return "water"
    if "highway" in tags:
        return "highway"
    if "leisure" in tags:
        return "leisure"
    if "landuse" in tags:
        return "landuse"
    if "amenity" in tags:
        return "amenity"
    if "shop" in tags:
        return "shop"
    return "other"


def should_be_polygon(tags: dict) -> bool:
    """Determine if a way should be rendered as a Polygon."""
    for key in POLYGON_TAGS:
        if key in tags:
            return True
        if tags.get("natural") == "water":
            return True
    return False


def resolve_way_coords(way_nds: list, node_index: dict) -> list:
    """Resolve node IDs to [lon, lat] coordinates."""
    coords = []
    for nd in way_nds:
        if nd in node_index:
            n = node_index[nd]
            coords.append([n["lon"], n["lat"]])
    return coords


def way_is_closed(coords: list) -> bool:
    return len(coords) >= 4 and coords[0] == coords[-1]


def main():
    queries = build_queries()
    all_elements = []
    seen_ids = set()
    stats = {}

    for i, (label, query_text) in enumerate(queries):
        if i > 0:
            print(f"  Waiting {QUERY_DELAY}s...")
            time.sleep(QUERY_DELAY)
        data = overpass_query(query_text, label)
        elements = data.get("elements", [])
        new_count = 0
        for el in elements:
            key = (el["type"], el["id"])
            if key not in seen_ids:
                seen_ids.add(key)
                all_elements.append(el)
                new_count += 1
        stats[label] = {"total": len(elements), "new": new_count}

    print("\n--- Query Stats ---")
    for label, s in stats.items():
        print(f"  {label}: {s['total']} elements ({s['new']} new after dedup)")
    print(f"  Total unique elements: {len(all_elements)}")

    # Build node index
    node_index = {}
    for el in all_elements:
        if el["type"] == "node":
            node_index[el["id"]] = el

    # Build way index (needed for relations)
    way_index = {}
    for el in all_elements:
        if el["type"] == "way":
            way_index[el["id"]] = el

    features = []
    way_count = 0
    node_feature_count = 0
    relation_count = 0

    # Process ways
    for el in all_elements:
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        if not tags:
            continue  # skip bare geometry ways (just nodes)

        nds = el.get("nodes", [])
        coords = resolve_way_coords(nds, node_index)
        if len(coords) < 2:
            continue

        category = categorize(tags)
        props = dict(tags)
        props["@id"] = f"way/{el['id']}"
        props["@category"] = category

        if should_be_polygon(tags) and way_is_closed(coords):
            geom = {"type": "Polygon", "coordinates": [coords]}
        else:
            geom = {"type": "LineString", "coordinates": coords}

        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": props,
        })
        way_count += 1

    # Process relations (multipolygon water bodies)
    for el in all_elements:
        if el["type"] != "relation":
            continue
        tags = el.get("tags", {})
        if not tags:
            continue

        category = categorize(tags)
        props = dict(tags)
        props["@id"] = f"relation/{el['id']}"
        props["@category"] = category

        members = el.get("members", [])
        outer_ways = [m for m in members if m.get("role") == "outer" and m.get("type") == "way"]

        for ow in outer_ways:
            way_id = ow["ref"]
            way_el = way_index.get(way_id)
            if not way_el:
                continue
            nds = way_el.get("nodes", [])
            coords = resolve_way_coords(nds, node_index)
            if len(coords) < 4:
                continue
            if not way_is_closed(coords):
                continue

            geom = {"type": "Polygon", "coordinates": [coords]}
            feat_props = dict(props)
            feat_props["@outer_way"] = f"way/{way_id}"
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": feat_props,
            })
            relation_count += 1

    # Process tagged nodes (amenities, shops)
    for el in all_elements:
        if el["type"] != "node":
            continue
        tags = el.get("tags", {})
        if not tags:
            continue

        category = categorize(tags)
        if category == "other":
            continue

        props = dict(tags)
        props["@id"] = f"node/{el['id']}"
        props["@category"] = category

        geom = {"type": "Point", "coordinates": [el["lon"], el["lat"]]}
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": props,
        })
        node_feature_count += 1

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    # Category breakdown
    cat_counts = defaultdict(int)
    geom_counts = defaultdict(int)
    for f in features:
        cat_counts[f["properties"].get("@category", "?")] += 1
        geom_counts[f["geometry"]["type"]] += 1

    print(f"\n--- Final GeoJSON ---")
    print(f"  Total features: {len(features)}")
    print(f"    from ways: {way_count}")
    print(f"    from relations (outer): {relation_count}")
    print(f"    from nodes: {node_feature_count}")
    print(f"\n  By category:")
    for cat in sorted(cat_counts):
        print(f"    {cat}: {cat_counts[cat]}")
    print(f"\n  By geometry type:")
    for gt in sorted(geom_counts):
        print(f"    {gt}: {geom_counts[gt]}")

    out_path = "/Users/york_z/Desktop/IDEA地图-agent模拟/Synthetic_Socio_Wind_Tunnel/data/lanecove_osm.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)

    file_size_mb = len(json.dumps(geojson, ensure_ascii=False)) / (1024 * 1024)
    print(f"\n  Saved to: {out_path}")
    print(f"  File size: {file_size_mb:.2f} MB")
    print("\nDone!")


if __name__ == "__main__":
    main()
