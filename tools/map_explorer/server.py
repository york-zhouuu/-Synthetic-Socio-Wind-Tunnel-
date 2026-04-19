"""
Map Explorer - Flask dev server.

Endpoints:
  GET /                              → index.html
  GET /api/map                       → full map data (god's-eye, for rendering all polygons)
  GET /api/agent/<id>/knowledge      → what this agent knows (their subjective map)
  GET /api/agent/<id>/location/<lid> → agent-perspective detail for a location
  GET /api/agent/<id>/scene/<lid>    → current scene at location
  GET /api/perception/<lid>          → raw perceptual scope (visible/audible)
"""

import sys
from pathlib import Path
from flask import Flask, jsonify, send_from_directory

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json as _json
import math as _math

from synthetic_socio_wind_tunnel.cartography.lanecove import (
    create_atlas_from_osm,
    OSM_DATA_PATH, ATLAS_CACHE_PATH, PROJ_CENTER_PATH,
)
from tools.map_explorer.demo_map import (
    create_atlas, create_ledger_with_demo_knowledge,
)
from synthetic_socio_wind_tunnel.map_service.service import MapService
from synthetic_socio_wind_tunnel.atlas.models import Building, OutdoorArea
from synthetic_socio_wind_tunnel.ledger.service import Ledger

app = Flask(__name__, static_folder="static")
STATIC_DIR = Path(__file__).parent / "static"

# ── Bootstrap ──────────────────────────────────────────────────────────────────
context_layers = {"water": [], "landuse": [], "pois": []}  # extra visual layers

if ATLAS_CACHE_PATH.exists() or OSM_DATA_PATH.exists():
    print("Loading Lane Cove map...")
    atlas = create_atlas_from_osm()
    ledger = Ledger()

    # Extract water + landuse from GeoJSON for visual context
    # Load EXACT projection center saved by the importer (ensures alignment)
    if OSM_DATA_PATH.exists() and PROJ_CENTER_PATH.exists():
        with open(OSM_DATA_PATH, "r", encoding="utf-8") as _f:
            _raw = _json.load(_f)
        with open(PROJ_CENTER_PATH, "r") as _f:
            _pc = _json.load(_f)

        _clat = _pc["center_lat"]
        _clon = _pc["center_lon"]
        _m_lat = 111320.0
        _m_lon = 111320.0 * _math.cos(_math.radians(_clat))

        _SOUTH_CLIP = -33.835
        _WEST_CLIP = 151.148  # cut off west-of-river isolated land

        def _proj(lon, lat):
            return [(lon - _clon) * _m_lon, -(lat - _clat) * _m_lat]

        for _feat in _raw["features"]:
            _props = _feat["properties"]
            _g = _feat["geometry"]
            _cat = None
            if _props.get("natural") == "water" or "waterway" in _props:
                _cat = "water"
            elif "landuse" in _props:
                _cat = "landuse"
            if not _cat:
                continue

            if _g["type"] == "Polygon":
                ring = _g["coordinates"][0]
                avg_lat = sum(c[1] for c in ring) / len(ring)
                avg_lon = sum(c[0] for c in ring) / len(ring)
                # Clip: south of harbour or west of river (isolated land)
                if _cat != "water" and (avg_lat < _SOUTH_CLIP or avg_lon < _WEST_CLIP):
                    continue
                pts = [_proj(c[0], c[1]) for c in ring]
                context_layers[_cat].append({
                    "type": "polygon", "points": pts,
                    "subtype": _props.get("landuse", _props.get("natural", "water")),
                    "name": _props.get("name", ""),
                })
            elif _g["type"] == "LineString":
                pts = [_proj(c[0], c[1]) for c in _g["coordinates"]]
                context_layers[_cat].append({
                    "type": "line", "points": pts,
                    "subtype": _props.get("waterway", "stream"),
                    "name": _props.get("name", ""),
                })
        # Extract POI points (cafes, restaurants, shops, banks, etc.)
        _POI_TYPES = {
            "cafe", "restaurant", "fast_food", "bar", "pub",
            "bank", "pharmacy", "clinic", "dentist", "doctors",
            "place_of_worship", "library", "community_centre",
            "childcare", "kindergarten", "school",
            "post_office", "car_wash", "veterinary",
        }
        for _feat in _raw["features"]:
            _g = _feat["geometry"]
            if _g["type"] != "Point":
                continue
            _props = _feat["properties"]
            _name = _props.get("name", "")
            if not _name:
                continue  # skip unnamed POIs
            _amenity = _props.get("amenity", "")
            _shop = _props.get("shop", "")
            if not _amenity and not _shop:
                continue
            _lat, _lon = _g["coordinates"][1], _g["coordinates"][0]
            if _lat < _SOUTH_CLIP or _lon < _WEST_CLIP:
                continue
            _pt = _proj(_lon, _lat)
            _poi_type = _amenity or f"shop:{_shop}"
            context_layers["pois"].append({
                "point": _pt,
                "name": _name,
                "type": _poi_type,
                "cuisine": _props.get("cuisine", ""),
            })
        print(f"Context layers: {len(context_layers['water'])} water, {len(context_layers['landuse'])} landuse, {len(context_layers['pois'])} POIs")
else:
    print("No OSM data found, using fictional demo map")
    atlas = create_atlas()
    ledger = create_ledger_with_demo_knowledge(atlas)

map_svc = MapService(atlas, ledger)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _polygon_points(polygon) -> list[list[float]]:
    return [[v.x, v.y] for v in polygon.vertices]


def _loc_base(loc_id: str) -> dict | None:
    b = atlas.get_building(loc_id)
    if b:
        return {
            "id": b.id,
            "name": b.name,
            "type": "building",
            "subtype": b.building_type,
            "polygon": _polygon_points(b.polygon),
            "center": [b.center.x, b.center.y],
        }
    a = atlas.get_outdoor_area(loc_id)
    if a:
        return {
            "id": a.id,
            "name": a.name,
            "type": "street" if a.is_street else "outdoor",
            "subtype": a.area_type,
            "polygon": _polygon_points(a.polygon),
            "center": [a.center.x, a.center.y],
        }
    return None


def _build_adjacency() -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {}
    for conn in atlas.region.connections:
        adj.setdefault(conn.from_id, set()).add(conn.to_id)
        if conn.bidirectional:
            adj.setdefault(conn.to_id, set()).add(conn.from_id)
    return adj


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.route("/api/map")
def get_map():
    """
    God's-eye full map — used only for rendering polygons on canvas.
    Does NOT include social judgments. Just geometry + basic metadata.
    """
    region = atlas.region
    locations = []
    for bid in atlas.list_buildings():
        base = _loc_base(bid)
        if base:
            locations.append(base)
    for aid in atlas.list_outdoor_areas():
        base = _loc_base(aid)
        if base:
            locations.append(base)

    seen = set()
    connections = []
    for conn in region.connections:
        key = tuple(sorted([conn.from_id, conn.to_id]))
        if key not in seen:
            seen.add(key)
            f = _loc_base(conn.from_id)
            t = _loc_base(conn.to_id)
            if f and t:
                connections.append({
                    "from_id": conn.from_id,
                    "to_id": conn.to_id,
                    "from_center": f["center"],
                    "to_center": t["center"],
                    "path_type": conn.path_type,
                    "distance": conn.distance,
                })

    borders = []
    for border in atlas.list_borders():
        borders.append({
            "border_id": border.border_id,
            "name": border.name,
            "border_type": border.border_type,
            "side_a": list(border.side_a),
            "side_b": list(border.side_b),
            "permeability": border.permeability,
            "description": border.description,
        })

    return jsonify({
        "region": {
            "id": region.id,
            "name": region.name,
            "bounds_min": [region.bounds_min.x, region.bounds_min.y],
            "bounds_max": [region.bounds_max.x, region.bounds_max.y],
        },
        "locations": locations,
        "connections": connections,
        "borders": borders,
    })


@app.route("/api/context-layers")
def get_context_layers():
    """Water bodies and landuse areas for visual context."""
    return jsonify(context_layers)


@app.route("/api/agent/<agent_id>/knowledge")
def get_agent_knowledge(agent_id: str):
    """
    What does this agent know about the world?

    Returns only locations in the agent's knowledge map.
    Unknown locations are absent — informational borders in action.
    """
    destinations = map_svc.get_known_destinations(agent_id)
    return jsonify({
        "agent_id": agent_id,
        "known_locations": [
            {
                "loc_id": d.loc_id,
                "known_name": d.known_name,
                "familiarity": d.familiarity,
                "loc_type": d.loc_type,
                "subtype": d.subtype,
                "known_affordances": d.known_affordances,
                "subjective_impression": d.subjective_impression,
                "last_visit": d.last_visit,
                "visit_count": d.visit_count,
                "learned_from": d.learned_from,
                "center": d.center,
            }
            for d in destinations
        ],
    })


@app.route("/api/agent/<agent_id>/location/<loc_id>")
def get_agent_location(agent_id: str, loc_id: str):
    """
    Agent-perspective detail for a location.

    Content depth scales with familiarity:
    - HEARD_OF: only name + how learned
    - SEEN_EXTERIOR: + what's visible from outside
    - VISITED+: + full affordances + social trace
    """
    detail = map_svc.get_location_detail(agent_id, loc_id)
    if detail is None:
        # Agent doesn't know this place
        return jsonify({"error": "unknown", "message": "Agent has no knowledge of this location"}), 404

    return jsonify({
        "loc_id": detail.loc_id,
        "name": detail.name,
        "loc_type": detail.loc_type,
        "subtype": detail.subtype,
        "familiarity": detail.familiarity,
        "description": detail.description,
        "typical_sounds": detail.typical_sounds,
        "typical_smells": detail.typical_smells,
        "active_hours": detail.active_hours,
        "entry_signals": detail.entry_signals,
        "affordances": [
            {
                "activity_type": a.activity_type,
                "available_now": a.available_now,
                "time_range": a.time_range,
                "requires": a.requires,
                "language_of_service": a.language_of_service,
                "description": a.description,
                "capacity": a.capacity,
            }
            for a in detail.affordances
        ],
        "recent_activity": detail.recent_activity,
        "connections": detail.connections,
        "entities_present": [
            {
                "entity_id": e.entity_id,
                "name": e.name,
                "distance_m": e.distance_m,
                "activity": e.activity,
            }
            for e in detail.entities_present
        ],
    })


@app.route("/api/agent/<agent_id>/scene/<loc_id>")
def get_agent_scene(agent_id: str, loc_id: str):
    """Current scene from agent's perspective at a location."""
    scene = map_svc.get_current_scene(agent_id, loc_id)
    return jsonify({
        "agent_id": scene.agent_id,
        "location_id": scene.location_id,
        "location_name": scene.location_name,
        "familiarity": scene.familiarity,
        "ambient_sounds": scene.ambient_sounds,
        "ambient_smells": scene.ambient_smells,
        "weather": scene.weather,
        "entities_present": [
            {"entity_id": e.entity_id, "activity": e.activity}
            for e in scene.entities_present
        ],
        "affordances": [
            {
                "activity_type": a.activity_type,
                "time_range": a.time_range,
                "requires": a.requires,
                "language_of_service": a.language_of_service,
                "description": a.description,
            }
            for a in scene.affordances
        ],
        "visible_locations": scene.visible_locations,
        "audible_locations": scene.audible_locations,
        "recent_activity": scene.recent_activity,
    })


@app.route("/api/perception/<loc_id>")
def get_perception(loc_id: str):
    """Raw perceptual scope from a location (visible / audible)."""
    base = _loc_base(loc_id)
    if not base:
        return jsonify({"error": "not found"}), 404

    adj = _build_adjacency()
    direct = adj.get(loc_id, set())
    is_building = base["type"] == "building"

    if is_building:
        visible = {n for n in direct
                   if atlas.get_outdoor_area(n) is not None}
    else:
        visible = set(direct)

    audible: set[str] = set()
    for v in visible:
        for n2 in adj.get(v, set()):
            if n2 != loc_id and n2 not in visible:
                audible.add(n2)

    return jsonify({
        "origin": loc_id,
        "visible": list(visible),
        "audible": list(audible),
    })


if __name__ == "__main__":
    print("Map Explorer running at http://localhost:5050")
    app.run(debug=True, port=5050)
