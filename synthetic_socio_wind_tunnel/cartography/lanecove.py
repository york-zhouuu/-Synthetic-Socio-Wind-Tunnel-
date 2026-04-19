"""
Lane Cove 2066 scenario loader — production entry for loading the real
Lane Cove atlas from OSM / Overture-enriched GeoJSON, plus the synthesised
Riverview residential infill.

Was previously hosted at `tools/map_explorer/mock_map.py`; moved here so the
name reflects "production code for the Lane Cove scenario" rather than the
misleading `mock_*` prefix. The legacy path still re-exports via a shim.

Public API:
    create_atlas_from_osm(path=None, segment_length=60.0) -> Atlas
    _infill_riverview(region) -> Region   # private but exported for shim
"""
from __future__ import annotations

from pathlib import Path

from synthetic_socio_wind_tunnel.atlas.service import Atlas
from synthetic_socio_wind_tunnel.atlas.models import (
    ActivityAffordance, Building, Polygon, Coord,
)
from synthetic_socio_wind_tunnel.cartography.importer import GeoJSONImporter


# ── Data paths ────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
OSM_DATA_PATH = _DATA_DIR / "lanecove_osm.geojson"
ENRICHED_DATA_PATH = _DATA_DIR / "lanecove_enriched.geojson"
ATLAS_CACHE_PATH = _DATA_DIR / "lanecove_atlas.json"
PROJ_CENTER_PATH = _DATA_DIR / "lanecove_proj_center.json"  # saved projection center


def create_atlas_from_osm(
    path: Path | None = None,
    segment_length: float = 60.0,
) -> Atlas:
    """
    Load Lane Cove, NSW 2066 from cached Atlas JSON (fast),
    or fall back to importing from a GeoJSON source (slow, ~130s).

    Source selection (first hit wins):
      1. `path` argument if provided
      2. `data/lanecove_enriched.geojson` (multi-source conflation output)
      3. `data/lanecove_osm.geojson` (pure OSM baseline) — fallback
    """
    import json
    from synthetic_socio_wind_tunnel.atlas.models import Region

    # Try cached atlas first (loads in <2s)
    if ATLAS_CACHE_PATH.exists():
        print(f"Loading cached atlas from {ATLAS_CACHE_PATH.name}")
        with open(ATLAS_CACHE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        region = Region.model_validate(raw)
        return Atlas(region)

    # Pick source GeoJSON
    if path is not None:
        src = path
    elif ENRICHED_DATA_PATH.exists():
        src = ENRICHED_DATA_PATH
        print(f"[source] enriched multi-source GeoJSON: {src.name}")
    else:
        src = OSM_DATA_PATH
        print(f"[fallback] pure OSM: {src.name}")

    # Slow path: import from raw GeoJSON
    print(f"No cache found. Importing from {src.name} (this takes ~2 min)...")
    imp = GeoJSONImporter()
    # Clip to Lane Cove 2066 boundary — exclude Drummoyne (south of harbour)
    clip_bounds = {
        "min_lat": -33.835,  # cut off south-of-harbour land
        "max_lat": -33.798,
        "min_lon": 151.145,
        "max_lon": 151.178,
    }
    region = imp.import_file(
        src,
        bounds=clip_bounds,
        region_id="lane_cove",
        segment_length=segment_length,
    )
    region = region.model_copy(update={"name": "Lane Cove, NSW 2066"})

    # Post-filter: remove locations whose center is south of clip line
    # Clip line lat -33.835 → projected y = -(-33.835 - center_lat) * 111320
    # We compute what y threshold corresponds to, then filter
    _south_y = 2130  # approx y for lat -33.835
    _west_x = -1400  # approx x for lon 151.148 (west of river)
    # Actually compute from region bounds: the importer center is the data center
    # so we filter by checking if center.y > some threshold
    _filtered_buildings = {
        bid: b for bid, b in region.buildings.items()
        if b.center.y < _south_y and b.center.x > _west_x
    }
    _filtered_outdoor = {
        aid: a for aid, a in region.outdoor_areas.items()
        if a.center.y < _south_y and a.center.x > _west_x
    }
    # Also filter connections referencing removed locations
    _kept_ids = set(_filtered_buildings.keys()) | set(_filtered_outdoor.keys())
    _filtered_conns = tuple(
        c for c in region.connections
        if c.from_id in _kept_ids and c.to_id in _kept_ids
    )
    _removed = (len(region.buildings) - len(_filtered_buildings)) + (len(region.outdoor_areas) - len(_filtered_outdoor))
    if _removed > 0:
        region = region.model_copy(update={
            "buildings": _filtered_buildings,
            "outdoor_areas": _filtered_outdoor,
            "connections": _filtered_conns,
        })
        # Recalculate bounds
        _all = []
        for b in region.buildings.values(): _all.extend(b.polygon.vertices)
        for a in region.outdoor_areas.values(): _all.extend(a.polygon.vertices)
        if _all:
            from synthetic_socio_wind_tunnel.atlas.models import Coord
            region = region.model_copy(update={
                "bounds_min": Coord(x=min(c.x for c in _all), y=min(c.y for c in _all)),
                "bounds_max": Coord(x=max(c.x for c in _all), y=max(c.y for c in _all)),
            })
        print(f"Clipped {_removed} locations south of harbour")

    # Infill missing Riverview residential area (OSM has no building footprints there)
    region = _infill_riverview(region)

    # Save projection center for context layers to reuse
    with open(PROJ_CENTER_PATH, "w") as f:
        json.dump({"center_lat": imp.center_lat, "center_lon": imp.center_lon}, f)

    # Save cache for next time
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(ATLAS_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(region.model_dump(mode="json"), f, ensure_ascii=False)
    print(f"Saved cache to {ATLAS_CACHE_PATH.name}")

    return Atlas(region)


def _infill_riverview(region) -> "Region":
    """
    Fill OSM gaps in Riverview with continuous rows of house lots.

    Real Riverview pattern (from reference map):
    - Streets form a grid; between parallel streets = a BLOCK
    - Each block is filled with tightly packed rectangular lots
    - Lot frontage: ~15-20m, lot depth: ~30-40m (to mid-block)
    - No gaps between lots — they share side fences
    - Houses occupy ~60-80% of each lot footprint, set back from the street
    """
    import math
    import random

    random.seed(42)

    ZONE_X = (-800, 950)
    ZONE_Y = (500, 2100)
    # Only skip paths/trails — residential footways and service roads DO have houses next to them
    SKIP_HIGHWAYS = {"path", "steps", "cycleway", "track"}
    SCHOOL_ZONE = ((-750, -350), (1100, 2100))

    # ── Existing buildings (for collision) ──
    existing = [(b.center.x, b.center.y) for b in region.buildings.values()]

    def has_collision(hx, hy, radius=10.0):
        for ex, ey in existing:
            if abs(ex - hx) < radius and abs(ey - hy) < radius:
                return True
        return False

    def in_school_zone(x, y):
        return SCHOOL_ZONE[0][0] < x < SCHOOL_ZONE[0][1] and SCHOOL_ZONE[1][0] < y < SCHOOL_ZONE[1][1]

    park_centers = []
    for oa in region.outdoor_areas.values():
        if oa.area_type in ("park", "playground", "garden"):
            c = oa.center
            if ZONE_X[0] < c.x < ZONE_X[1] and ZONE_Y[0] < c.y < ZONE_Y[1]:
                vs = oa.polygon.vertices
                r = math.sqrt((max(v.x for v in vs)-min(v.x for v in vs))**2 +
                              (max(v.y for v in vs)-min(v.y for v in vs))**2) / 2
                park_centers.append((c.x, c.y, max(r, 20)))

    def in_park(x, y):
        return any((x-px)**2 + (y-py)**2 < pr**2 for px, py, pr in park_centers)

    # ── House shape: irregular L/T polygons within each lot ──
    def _make_house(hx, hy, ux, uy, nx, ny, lot_hw, lot_depth):
        """Create a house polygon within a lot. House occupies ~70% of lot area."""
        # House sits within the lot: narrower than lot, set back from front
        front_setback = random.uniform(3, 6)  # from road-facing lot edge
        rear_margin = random.uniform(5, 12)   # backyard
        side_margin = random.uniform(1.0, 2.5)  # side passage

        house_hw = lot_hw - side_margin  # half-width of house
        house_start = front_setback  # from lot front edge
        house_end = lot_depth - rear_margin  # from lot front edge
        house_depth = house_end - house_start
        if house_depth < 6 or house_hw < 4:
            return None

        # House center in local lot coords (along-road=u, perp=n)
        # Lot front is at perp offset from road; house pushed back by front_setback
        center_along = 0  # centered in lot width
        center_perp = house_start + house_depth / 2  # pushed back from front

        # Choose shape
        shape = random.choices(["rect", "L", "notch"], weights=[40, 35, 25])[0]
        hw = house_hw
        hd = house_depth / 2

        if shape == "rect":
            pts = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
            # Slight jitter
            pts = [(px + random.uniform(-0.3, 0.3), py + random.uniform(-0.3, 0.3))
                   for px, py in pts]

        elif shape == "L":
            cut_w = hw * random.uniform(0.25, 0.45)
            cut_d = hd * random.uniform(0.3, 0.5)
            corner = random.choice([0, 1, 2, 3])
            if corner == 0:  # top-right
                pts = [(-hw, -hd), (hw, -hd), (hw, hd-cut_d), (hw-cut_w, hd-cut_d), (hw-cut_w, hd), (-hw, hd)]
            elif corner == 1:  # top-left
                pts = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw+cut_w, hd), (-hw+cut_w, hd-cut_d), (-hw, hd-cut_d)]
            elif corner == 2:  # bottom-right
                pts = [(-hw, -hd), (hw-cut_w, -hd), (hw-cut_w, -hd+cut_d), (hw, -hd+cut_d), (hw, hd), (-hw, hd)]
            else:  # bottom-left
                pts = [(-hw, -hd+cut_d), (-hw+cut_w, -hd+cut_d), (-hw+cut_w, -hd), (hw, -hd), (hw, hd), (-hw, hd)]

        else:  # notch
            nw = hw * random.uniform(0.15, 0.3)
            nd = hd * random.uniform(0.15, 0.25)
            npos = random.uniform(-hw * 0.3, hw * 0.3)
            pts = [
                (-hw, -hd), (npos-nw, -hd), (npos-nw, -hd+nd), (npos+nw, -hd+nd),
                (npos+nw, -hd), (hw, -hd), (hw, hd), (-hw, hd),
            ]

        # Transform: local lot coords → world coords
        # local x = along road (u), local y = perpendicular from road (n)
        world_pts = []
        for lx, ly in pts:
            # lx is along-road offset, ly is perp offset from house center
            wy_offset = center_perp + ly  # total perp from lot front
            wx = hx + lx * ux + wy_offset * nx
            wy = hy + lx * uy + wy_offset * ny
            world_pts.append(Coord(x=wx, y=wy))
        return Polygon(vertices=tuple(world_pts))

    # ── Main: fill lots along each street segment ──
    new_buildings = dict(region.buildings)
    new_connections: list = list(region.connections)
    count = 0

    # Import Connection here to avoid polluting module top when this function
    # is not called. Placed locally so the mock stays self-contained.
    from synthetic_socio_wind_tunnel.atlas.models import Connection

    for aid, area in region.outdoor_areas.items():
        if area.area_type != "street":
            continue
        cx, cy = area.center.x, area.center.y
        if not (ZONE_X[0] < cx < ZONE_X[1] and ZONE_Y[0] < cy < ZONE_Y[1]):
            continue
        highway = area.osm_tags.get("highway", "residential")
        if highway in SKIP_HIGHWAYS:
            continue
        verts = area.polygon.vertices
        if len(verts) != 4:
            continue

        v0, v1, v2, v3 = verts[0], verts[1], verts[2], verts[3]
        rdx, rdy = v1.x - v0.x, v1.y - v0.y
        road_len = math.sqrt(rdx**2 + rdy**2)
        if road_len < 15:
            continue

        ux, uy = rdx / road_len, rdy / road_len
        nx, ny = -uy, ux
        half_w = math.sqrt((v3.x-v0.x)**2 + (v3.y-v0.y)**2) / 2

        # Centerline start/end
        cl_x0, cl_y0 = (v0.x+v3.x)/2, (v0.y+v3.y)/2
        cl_x1, cl_y1 = (v1.x+v2.x)/2, (v1.y+v2.y)/2

        # Adjust lot depth based on road type
        is_minor = highway in ("footway", "service", "pedestrian", "living_street")

        for side in (+1, -1):
            # Fill the road frontage with continuous lots
            cursor = 0.0
            while cursor < road_len:
                lot_frontage = random.uniform(13, 20)
                # Minor roads: shallower lots (only one side typically has houses)
                if is_minor:
                    lot_depth = random.uniform(15, 25)
                else:
                    lot_depth = random.uniform(28, 40)

                if cursor + lot_frontage > road_len:
                    break

                lot_center_t = (cursor + lot_frontage / 2) / road_len

                # Lot front edge center (on road edge)
                front_x = cl_x0 + lot_center_t * (cl_x1 - cl_x0) + side * half_w * nx
                front_y = cl_y0 + lot_center_t * (cl_y1 - cl_y0) + side * half_w * ny

                # House center for collision check (roughly mid-lot)
                hx = front_x + side * (lot_depth * 0.4) * nx
                hy = front_y + side * (lot_depth * 0.4) * ny

                cursor += lot_frontage

                if not (ZONE_X[0] < hx < ZONE_X[1] and ZONE_Y[0] < hy < ZONE_Y[1]):
                    continue
                if in_school_zone(hx, hy):
                    continue
                if in_park(hx, hy):
                    continue
                if has_collision(hx, hy):
                    continue

                # Create house within lot
                # For side=+1: perpendicular points from road toward +nx
                # For side=-1: perpendicular points from road toward -nx
                # We need nx to always point AWAY from road
                out_nx = side * nx
                out_ny = side * ny

                poly = _make_house(front_x, front_y, ux, uy, out_nx, out_ny,
                                   lot_frontage / 2, lot_depth)
                if poly is None:
                    continue

                bid = f"rv_{count}"
                new_buildings[bid] = Building(
                    id=bid, name="House", polygon=poly,
                    building_type="residential",
                    # Keep parity with importer._default_residential_affordance
                    # so agent home enumeration sees these synthesized homes too.
                    affordances=(ActivityAffordance(
                        activity_type="reside",
                        capacity=1,
                        description="residential dwelling (inferred, synthesized)",
                    ),),
                )
                # Wire the infilled house to the street segment it was placed
                # alongside so it isn't isolated in the connectivity graph.
                new_connections.append(Connection(
                    from_id=bid,
                    to_id=aid,
                    path_type="entrance",
                    distance=max(1.0, lot_depth * 0.4),
                ))
                existing.append((hx, hy))
                count += 1

    print(f"Riverview infill: placed {count} houses along streets")
    return region.model_copy(update={
        "buildings": new_buildings,
        "connections": tuple(new_connections),
    })
