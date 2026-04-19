"""
Multi-source GeoJSON conflation for the Lane Cove pipeline.

Merges three inputs into a single enriched FeatureCollection:
  1. OpenStreetMap export (baseline polygons + roads, hand-curated names)
  2. Overture Buildings theme (dense polygons, height / class attributes)
  3. Overture Places theme (POI points with name + category)

Rules (see openspec/changes/enrich-lanecove-map/design.md):
  * OSM wins on name/amenity/shop — never overwritten.
  * Overture Building whose centroid sits inside an OSM building → merge
    Overture-only attributes into the OSM feature (height, class, etc.).
  * Overture Building whose centroid sits outside any OSM polygon → append
    as a new feature with `overture:primary_source="overture_buildings"`.
  * Overture Place whose coord sits inside a host building → append an
    ActivityAffordance dict to the host's `properties["affordances"]`.
    Also back-fill `name` if the host is anonymous (matches `^building_\\d+$`).
  * Overture Place without a host → if confidence ≥ floor, emit as a small
    stub Polygon (edge = `stub_size_m`). Below floor → dropped + logged.

Zero third-party deps: ray-casting point-in-polygon in pure Python.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Category → activity mapping (Overture taxonomy → our ActivityAffordance)
# ---------------------------------------------------------------------------

_CATEGORY_TO_ACTIVITY: dict[str, str] = {
    "eat_and_drink": "eat",
    "shopping": "shop",
    "education": "study",
    "health": "medical",
    "community_and_government": "civic",
    "arts_and_entertainment": "entertainment",
    "accommodation": "stay",
    "beauty_and_spa": "personal_care",
    "financial_service": "civic",
    "travel": "transit",
    "active_life": "recreation",
    "professional_services": "work",
    "automotive": "transit",
    "religious_organization": "civic",
    "landmark_and_historical_building": "visit",
}


def category_to_activity(category: str | None) -> str:
    """Map an Overture category like 'eat_and_drink.coffee' to our coarse
    activity_type. Unknown categories fall back to 'visit'."""
    if not category:
        return "visit"
    prefix = category.split(".", 1)[0]
    return _CATEGORY_TO_ACTIVITY.get(prefix, "visit")


# ---------------------------------------------------------------------------
# Pure-Python geometry helpers
# ---------------------------------------------------------------------------


def _ring_contains(ring: list[list[float]], x: float, y: float) -> bool:
    """Ray-casting point-in-ring test. `ring` is a list of [lon, lat]."""
    n = len(ring)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        # Edge crosses horizontal ray at y
        if (yi > y) != (yj > y):
            x_at = (xj - xi) * (y - yi) / (yj - yi + 1e-18) + xi
            if x < x_at:
                inside = not inside
        j = i
    return inside


def _polygon_contains(coords: list[list[list[float]]], x: float, y: float) -> bool:
    """GeoJSON polygon contains: outer ring minus holes."""
    if not coords:
        return False
    if not _ring_contains(coords[0], x, y):
        return False
    for hole in coords[1:]:
        if _ring_contains(hole, x, y):
            return False
    return True


def _feature_centroid(feature: dict) -> tuple[float, float] | None:
    """Approximate centroid of a polygon feature (average of outer-ring vertices)."""
    geom = feature.get("geometry") or {}
    if geom.get("type") != "Polygon":
        return None
    coords = geom.get("coordinates") or []
    if not coords or not coords[0]:
        return None
    ring = coords[0]
    n = len(ring)
    if n == 0:
        return None
    sx = sum(pt[0] for pt in ring) / n
    sy = sum(pt[1] for pt in ring) / n
    return sx, sy


def _feature_bbox(feature: dict) -> tuple[float, float, float, float] | None:
    """(min_lon, min_lat, max_lon, max_lat) of a polygon feature."""
    geom = feature.get("geometry") or {}
    if geom.get("type") != "Polygon":
        return None
    coords = geom.get("coordinates") or []
    if not coords or not coords[0]:
        return None
    ring = coords[0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return (min(lons), min(lats), max(lons), max(lats))


def _stub_square(lon: float, lat: float, edge_m: float) -> dict:
    """Return a small square Polygon geometry (GeoJSON) centred at (lon,lat)."""
    # Convert metres to degrees (equirectangular approx).
    d_lat = edge_m / 111320.0
    # cos(lat) ≈ constant over a small square
    import math
    d_lon = edge_m / (111320.0 * max(math.cos(math.radians(lat)), 0.1))
    half_lon = d_lon / 2
    half_lat = d_lat / 2
    ring = [
        [lon - half_lon, lat - half_lat],
        [lon + half_lon, lat - half_lat],
        [lon + half_lon, lat + half_lat],
        [lon - half_lon, lat + half_lat],
        [lon - half_lon, lat - half_lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


_ANONYMOUS_NAME_RE = re.compile(r"^building_\d+$")


def _is_anonymous_name(name: str | None) -> bool:
    return not name or bool(_ANONYMOUS_NAME_RE.match(name))


def _is_osm_building(feature: dict) -> bool:
    geom = feature.get("geometry") or {}
    props = feature.get("properties") or {}
    return geom.get("type") == "Polygon" and "building" in props


def _overture_class(feature: dict) -> str | None:
    props = feature.get("properties") or {}
    # Overture buildings schema: { "class": "...", "names": {"primary": ...}, ... }
    return props.get("class") or props.get("building:class")


def _overture_place_category(feature: dict) -> str | None:
    props = feature.get("properties") or {}
    cats = props.get("categories") or {}
    if isinstance(cats, dict):
        return cats.get("primary") or (cats.get("alternate", [None]) or [None])[0]
    return None


def _overture_place_name(feature: dict) -> str | None:
    props = feature.get("properties") or {}
    names = props.get("names") or {}
    if isinstance(names, dict):
        return names.get("primary") or names.get("common")
    return None


def _overture_place_confidence(feature: dict) -> float:
    props = feature.get("properties") or {}
    c = props.get("confidence")
    try:
        return float(c) if c is not None else 1.0
    except (TypeError, ValueError):
        return 0.0


@dataclass
class MergeStats:
    """Observable counters from a conflation run."""
    osm_features_in: int = 0
    overture_buildings_merged: int = 0
    overture_buildings_added: int = 0
    places_bound: int = 0
    places_stubbed: int = 0
    places_dropped: int = 0
    anonymous_names_replaced: int = 0
    dropped_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "osm_features_in": self.osm_features_in,
            "overture_buildings_merged": self.overture_buildings_merged,
            "overture_buildings_added": self.overture_buildings_added,
            "places_bound": self.places_bound,
            "places_stubbed": self.places_stubbed,
            "places_dropped": self.places_dropped,
            "anonymous_names_replaced": self.anonymous_names_replaced,
            "dropped_reasons_sample": self.dropped_reasons[:20],
        }


def _load_fc(path: str | Path | None) -> list[dict]:
    if path is None:
        return []
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        return list(data.get("features") or [])
    return []


def _affordance_from_place(place: dict) -> dict:
    """Render an Overture Place feature as an affordance dict embeddable in
    `properties["affordances"]`."""
    name = _overture_place_name(place)
    category = _overture_place_category(place)
    activity = category_to_activity(category)
    return {
        "activity_type": activity,
        "source": "overture_places",
        "category": category or "unknown",
        "name": name or "",
        "confidence": _overture_place_confidence(place),
        "description": f"{category or 'place'} ({name or 'unnamed'}) — via Overture",
    }


def merge_sources(
    osm_path: str | Path | None,
    overture_buildings_path: str | Path | None = None,
    overture_places_path: str | Path | None = None,
    *,
    place_confidence_floor: float = 0.5,
    stub_size_m: float = 8.0,
) -> tuple[dict, MergeStats]:
    """Merge OSM + Overture Buildings + Overture Places into one enriched
    FeatureCollection. Returns (geojson_dict, stats).

    Any of the paths may be None / missing; the function degrades gracefully
    to whatever is present.
    """
    osm_features = _load_fc(osm_path)
    overture_bldgs = _load_fc(overture_buildings_path)
    overture_places = _load_fc(overture_places_path)

    stats = MergeStats(osm_features_in=len(osm_features))

    # Output accumulator; we mutate `properties` on these features in-place.
    output_features: list[dict] = []
    osm_building_indices: list[int] = []  # indices into output_features

    for feat in osm_features:
        # Make a shallow copy of properties so we can mutate without aliasing
        # the caller's dict (paranoia: the caller may cache).
        props = dict(feat.get("properties") or {})
        new_feat = {**feat, "properties": props}
        output_features.append(new_feat)
        if _is_osm_building(new_feat):
            osm_building_indices.append(len(output_features) - 1)

    # --------- Step 2: Overture Buildings dedup vs OSM ---------

    # Build a simple spatial index over OSM buildings (by bbox), bucket by
    # rounded degrees to avoid O(n·m) on ~3k × ~6k pairs.
    BUCKET = 0.002  # ~200m; buildings wider than this are rare in this region
    buckets: dict[tuple[int, int], list[int]] = {}
    for idx in osm_building_indices:
        b = _feature_bbox(output_features[idx])
        if b is None:
            continue
        # Store against every bucket the bbox touches
        x0 = int(b[0] / BUCKET)
        y0 = int(b[1] / BUCKET)
        x1 = int(b[2] / BUCKET)
        y1 = int(b[3] / BUCKET)
        for bx in range(x0, x1 + 1):
            for by in range(y0, y1 + 1):
                buckets.setdefault((bx, by), []).append(idx)

    def _find_osm_host_for_point(lon: float, lat: float) -> int | None:
        bx = int(lon / BUCKET)
        by = int(lat / BUCKET)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for idx in buckets.get((bx + dx, by + dy), ()):
                    g = output_features[idx].get("geometry") or {}
                    coords = g.get("coordinates") or []
                    if _polygon_contains(coords, lon, lat):
                        return idx
        return None

    overture_added_indices: list[int] = []

    for ov_bldg in overture_bldgs:
        g = ov_bldg.get("geometry") or {}
        if g.get("type") != "Polygon":
            continue
        centroid = _feature_centroid(ov_bldg)
        if centroid is None:
            continue
        cx, cy = centroid
        host_idx = _find_osm_host_for_point(cx, cy)

        ov_props = ov_bldg.get("properties") or {}
        ov_names = ov_props.get("names") or {}
        ov_class = _overture_class(ov_bldg)
        ov_height = ov_props.get("height")
        ov_num_floors = ov_props.get("num_floors")
        ov_confidence = ov_props.get("confidence")
        ov_sources = ov_props.get("sources") or []

        extra = {
            "overture:class": ov_class,
            "overture:height": ov_height,
            "overture:num_floors": ov_num_floors,
            "overture:names.primary": (ov_names.get("primary")
                                       if isinstance(ov_names, dict) else None),
            "overture:confidence": ov_confidence,
            "overture:sources": ov_sources,
        }
        # Strip None values — we only want to record what we actually have.
        extra = {k: v for k, v in extra.items() if v is not None}

        if host_idx is not None:
            host_props = output_features[host_idx]["properties"]
            for k, v in extra.items():
                host_props.setdefault(k, v)
            host_props.setdefault("overture:primary_source", "osm")
            stats.overture_buildings_merged += 1
        else:
            new_props = dict(ov_props)
            new_props.update(extra)
            new_props["building"] = new_props.get("building", "yes")
            new_props["overture:primary_source"] = "overture_buildings"
            # Promote Overture name if present
            ov_primary = extra.get("overture:names.primary")
            if ov_primary and "name" not in new_props:
                new_props["name"] = ov_primary
            new_feat = {
                "type": "Feature",
                "geometry": g,
                "properties": new_props,
            }
            output_features.append(new_feat)
            overture_added_indices.append(len(output_features) - 1)
            # Update buckets so subsequent Places can bind to this new building
            b = _feature_bbox(new_feat)
            if b is not None:
                idx = len(output_features) - 1
                x0 = int(b[0] / BUCKET)
                y0 = int(b[1] / BUCKET)
                x1 = int(b[2] / BUCKET)
                y1 = int(b[3] / BUCKET)
                for bx in range(x0, x1 + 1):
                    for by in range(y0, y1 + 1):
                        buckets.setdefault((bx, by), []).append(idx)
            stats.overture_buildings_added += 1

    # --------- Step 3 & 4: Overture Places → host building or stub ---------

    for place in overture_places:
        g = place.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        coords = g.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])

        host_idx = _find_osm_host_for_point(lon, lat)
        confidence = _overture_place_confidence(place)
        affordance = _affordance_from_place(place)
        place_name = _overture_place_name(place)
        place_category = _overture_place_category(place)

        if host_idx is not None:
            host_props = output_features[host_idx]["properties"]
            host_props.setdefault("affordances", []).append(affordance)
            # Promote POI name into anonymous hosts
            if _is_anonymous_name(host_props.get("name")) and place_name:
                host_props["name"] = place_name
                stats.anonymous_names_replaced += 1
            # Expose category in the host tag namespace
            if place_category:
                host_props.setdefault("overture:place:category", place_category)
            stats.places_bound += 1
            continue

        if confidence < place_confidence_floor:
            stats.places_dropped += 1
            reason = f"low_confidence:{confidence:.2f}:{place_category or '?'}"
            stats.dropped_reasons.append(reason)
            continue

        # Stub: synthesise a small square Polygon as a minimal host.
        stub_geom = _stub_square(lon, lat, stub_size_m)
        stub_props: dict = {
            "building": "yes",
            "name": place_name or "",
            "overture:primary_source": "overture_places",
            "overture:place:category": place_category,
            "overture:confidence": confidence,
            "affordances": [affordance],
        }
        # If we have the Overture Place `categories`, use its prefix to give
        # the stub a reasonable building_type hint downstream.
        output_features.append({
            "type": "Feature",
            "geometry": stub_geom,
            "properties": stub_props,
        })
        stats.places_stubbed += 1

    return (
        {"type": "FeatureCollection", "features": output_features},
        stats,
    )


def write_feature_collection(fc: dict, out_path: str | Path) -> None:
    """Serialise a FeatureCollection to disk as compact JSON."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)


__all__ = [
    "merge_sources",
    "write_feature_collection",
    "category_to_activity",
    "MergeStats",
]
