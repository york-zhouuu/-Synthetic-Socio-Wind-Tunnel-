"""
GeoJSON Importer - Import real-world map data for community simulation.

Converts GeoJSON (from OpenStreetMap) into Atlas format with:
- Buildings with functional types extracted from OSM tags
- Street segments from road LineStrings (80m segments)
- Open spaces (parks, plazas) from leisure/landuse polygons
- Auto-inferred connections (building↔street, street↔street, intersections)

This is an OFFLINE tool — run before simulation starts.

Workflow:
    importer = GeoJSONImporter()
    region = importer.import_file("community.geojson", region_id="my_community")
    Atlas(region).to_json("atlas.json")
"""

from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Any

from synthetic_socio_wind_tunnel.atlas.models import (
    Region,
    Building,
    OutdoorArea,
    Connection,
    Coord,
    Polygon,
    Material,
    ActivityAffordance,
)


# ============================================================
# OSM tag → building_type mapping
# ============================================================

_AMENITY_TO_TYPE: dict[str, str] = {
    "cafe": "cafe",
    "restaurant": "restaurant",
    "bar": "bar",
    "pub": "bar",
    "fast_food": "restaurant",
    "ice_cream": "cafe",
    "library": "library",
    "school": "school",
    "university": "school",
    "kindergarten": "school",
    "childcare": "school",
    "prep_school": "school",
    "hospital": "hospital",
    "clinic": "hospital",
    "doctors": "hospital",
    "dentist": "hospital",
    "veterinary": "hospital",
    "pharmacy": "shop",
    "bank": "office",
    "post_office": "office",
    "community_centre": "community",
    "community_center": "community",
    "place_of_worship": "worship",
    "police": "government",
    "fire_station": "government",
    "townhall": "government",
    "theatre": "entertainment",
    "cinema": "entertainment",
    "fuel": "shop",
    "car_wash": "shop",
    "parking": "utility",
}

_SHOP_TO_TYPE: dict[str, str] = {
    "supermarket": "shop",
    "convenience": "shop",
    "bakery": "shop",
    "butcher": "shop",
    "greengrocer": "shop",
    "clothes": "shop",
    "hairdresser": "shop",
    "hardware": "shop",
    "books": "shop",
}

_BUILDING_TO_TYPE: dict[str, str] = {
    "residential": "residential",
    "apartments": "residential",
    "house": "residential",
    "detached": "residential",
    "terrace": "residential",
    "semidetached_house": "residential",
    "unit": "residential",
    "commercial": "commercial",
    "office": "office",
    "retail": "shop",
    "supermarket": "shop",
    "kiosk": "shop",
    "industrial": "industrial",
    "warehouse": "industrial",
    "church": "worship",
    "chapel": "worship",
    "mosque": "worship",
    "temple": "worship",
    "school": "school",
    "kindergarten": "school",
    "university": "school",
    "hospital": "hospital",
    "hotel": "hotel",
    "civic": "community",
    "public": "community",
    "garage": "utility",
    "shed": "utility",
    "roof": "utility",
    "carport": "utility",
}

_LEISURE_TO_AREA_TYPE: dict[str, str] = {
    "park": "park",
    "garden": "garden",
    "playground": "playground",
    "pitch": "playground",
    "sports_centre": "playground",
    "swimming_pool": "playground",
    "dog_park": "park",
    "nature_reserve": "park",
}

_HIGHWAY_WIDTHS: dict[str, float] = {
    "footway": 2.0,
    "path": 2.0,
    "pedestrian": 4.0,
    "steps": 2.0,
    "cycleway": 3.0,
    "residential": 6.0,
    "living_street": 5.0,
    "service": 4.0,
    "unclassified": 6.0,
    "tertiary": 7.0,
    "secondary": 8.0,
    "primary": 10.0,
    "trunk": 12.0,
}


class GeoJSONImporter:
    """
    Import GeoJSON data into Atlas format with full road network support.

    Produces a Region with:
    - Buildings extracted from polygon features with 'building' tag
    - Street segments from LineString features with 'highway' tag
    - Open spaces from polygon features with 'leisure'/'landuse' tags
    - Auto-inferred connections between all locations
    """

    def __init__(self):
        self._building_counter = 0
        self._area_counter = 0
        self._segment_counter = 0
        # Taken IDs — _make_id appends a counter on collision.
        self._used_ids: set[str] = set()
        # Saved after import for reuse by other layers
        self.center_lat: float = 0.0
        self.center_lon: float = 0.0

    def import_file(
        self,
        path: str | Path,
        bounds: dict[str, float] | None = None,
        scale: float = 10000.0,
        region_id: str = "imported",
        segment_length: float = 80.0,
    ) -> Region:
        """
        Import GeoJSON file.

        Args:
            path: Path to GeoJSON file
            bounds: Optional crop bounds {min_lat, max_lat, min_lon, max_lon}
            scale: Coordinate scale factor (degrees → meters approx)
            region_id: ID for the output region
            segment_length: Length of each street segment in projected units
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self.import_data(data, bounds, scale, region_id, segment_length)

    def import_data(
        self,
        geojson: dict[str, Any],
        bounds: dict[str, float] | None = None,
        scale: float = 10000.0,
        region_id: str = "imported",
        segment_length: float = 80.0,
    ) -> Region:
        """Import from GeoJSON dictionary."""
        features = geojson.get("features", [])

        if bounds:
            features = [f for f in features if self._in_bounds(f, bounds)]

        center_lat, center_lon = self._calculate_center(features)
        self.center_lat = center_lat
        self.center_lon = center_lon

        buildings: dict[str, Building] = {}
        outdoor_areas: dict[str, OutdoorArea] = {}
        # One list per OSM way so same-named ways don't overwrite each other's
        # adjacency chain (e.g. multiple "Burns Bay Road" ways).
        way_segments: list[list[str]] = []
        # Per-segment endpoint coords in the original (lon, lat) space, keyed
        # by rounded pair so that shared OSM nodes match exactly across roads.
        # Each seg_id → (start_key, end_key)
        segment_endpoints: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {}

        for feature in features:
            geom_type = feature.get("geometry", {}).get("type", "")
            props = feature.get("properties", {})

            if geom_type == "Polygon":
                if self._is_building(props):
                    building = self._extract_building(
                        feature, center_lat, center_lon, scale
                    )
                    if building:
                        buildings[building.id] = building
                elif self._is_area(props):
                    area = self._extract_outdoor_area(
                        feature, center_lat, center_lon, scale
                    )
                    if area:
                        outdoor_areas[area.id] = area

            elif geom_type == "LineString":
                if self._is_road(props):
                    segments, endpoints = self._extract_street_segments(
                        feature, center_lat, center_lon, scale, segment_length
                    )
                    for seg, ep in zip(segments, endpoints):
                        outdoor_areas[seg.id] = seg
                        segment_endpoints[seg.id] = ep

                    if segments:
                        way_segments.append([s.id for s in segments])

        # Calculate bounds
        all_coords: list[Coord] = []
        for b in buildings.values():
            all_coords.extend(b.polygon.vertices)
        for a in outdoor_areas.values():
            all_coords.extend(a.polygon.vertices)

        if all_coords:
            bounds_min = Coord(
                x=min(c.x for c in all_coords),
                y=min(c.y for c in all_coords),
            )
            bounds_max = Coord(
                x=max(c.x for c in all_coords),
                y=max(c.y for c in all_coords),
            )
        else:
            bounds_min = bounds_max = Coord(x=0, y=0)

        # Infer connections
        connections = self._infer_connections(
            buildings, outdoor_areas, way_segments, segment_endpoints,
        )

        return Region(
            id=region_id,
            name=region_id.replace("_", " ").title(),
            bounds_min=bounds_min,
            bounds_max=bounds_max,
            buildings=buildings,
            outdoor_areas=outdoor_areas,
            connections=tuple(connections),
        )

    # ========== Feature classification ==========

    def _is_building(self, props: dict) -> bool:
        return "building" in props

    def _is_area(self, props: dict) -> bool:
        """Check if this is an outdoor area for the Atlas (parks, playgrounds, etc.).

        Excludes landuse polygons (residential, industrial, etc.) — those are
        large zone-level overlays rendered as context layers, not interactive locations.
        """
        if "building" in props:
            return False
        if "leisure" in props:
            return True
        # Only include specific small-scale landuse types, not zone-level ones
        landuse = props.get("landuse", "")
        if landuse in ("village_green", "recreation_ground"):
            return True
        return False

    def _is_road(self, props: dict) -> bool:
        return "highway" in props

    # ========== Building extraction ==========

    def _extract_building(
        self,
        feature: dict,
        center_lat: float,
        center_lon: float,
        scale: float,
    ) -> Building | None:
        coords = feature.get("geometry", {}).get("coordinates", [])
        if not coords:
            return None

        ring = coords[0] if isinstance(coords[0][0], list) else coords
        vertices = tuple(
            self._project(c[1], c[0], center_lat, center_lon, scale)
            for c in ring if len(c) >= 2
        )

        if len(vertices) < 3:
            return None

        props = feature.get("properties", {})
        # Back-fill anonymous name from Overture when conflation left one.
        name = (props.get("name")
                or props.get("overture:names.primary")
                or f"building_{self._building_counter}")
        self._building_counter += 1

        polygon = Polygon(vertices=vertices)
        material = self._infer_material(props)
        building_type = self._infer_building_type(props)

        # Collect OSM + Overture tags (prefix kept so downstream can disambiguate).
        osm_tags: dict[str, str] = {}
        for key in ("amenity", "shop", "building", "cuisine", "opening_hours",
                     "name", "addr:street", "addr:housenumber"):
            if key in props:
                osm_tags[key] = str(props[key])
        for key, val in props.items():
            if key.startswith("overture:") and val is not None:
                osm_tags[key] = str(val)

        affordances = self._extract_affordances(props)
        floors = self._infer_floors(props)

        # Residential baseline semantics: every residential building gets a
        # default "reside" affordance so agents can enumerate homes. Richer
        # tenant / household info is a Phase 2 concern (see docs/agent_system).
        # The `source="inferred_default"` marker lets future data-driven
        # residential enrichment distinguish defaults from real signals.
        if building_type == "residential" and not any(
            a.activity_type == "reside" for a in affordances
        ):
            affordances = affordances + (self._default_residential_affordance(
                floors=floors, osm_tags=osm_tags,
            ),)

        return Building(
            id=self._make_id(name, "bldg"),
            name=name,
            polygon=polygon,
            building_type=building_type,
            osm_tags=osm_tags,
            exterior_material=material,
            floors=floors,
            entrance_coord=polygon.center,
            affordances=affordances,
        )

    def _default_residential_affordance(
        self, *, floors: int, osm_tags: dict[str, str],
    ) -> ActivityAffordance:
        """Produce a minimal "reside" affordance for a residential building.

        Extension points for Phase 2 (memory / social-graph / orchestrator):
          - dwelling_count: rough cap on how many agents can call this home
          - tenure / subtype: owner-occupied / rental / social_housing
          - household_profile: demographics from G-NAF / ABS mesh blocks
        For now we only encode the dwelling_count hint so an orchestrator
        can spread agents across buildings without overfilling any single one.
        """
        # Rough dwelling-count heuristic: 1 unit per floor, capped at 12 for
        # low-rise suburban reality. Buildings with explicit apartments will
        # carry building="apartments" already — we trust that signal.
        is_multi_unit = (
            osm_tags.get("building") == "apartments"
            or osm_tags.get("overture:class") == "residential" and floors >= 3
        )
        if is_multi_unit:
            dwelling_count = max(1, min(12, floors * 4))
        else:
            dwelling_count = 1

        desc = (f"residential dwelling ({dwelling_count} units, inferred)"
                if is_multi_unit else "residential dwelling (inferred)")
        return ActivityAffordance(
            activity_type="reside",
            capacity=dwelling_count,
            description=desc,
        )

    # Overture class → our building_type (coarse mapping).
    _OVERTURE_CLASS_TO_TYPE: dict[str, str] = {
        "residential": "residential",
        "commercial": "shop",
        "retail": "shop",
        "office": "office",
        "industrial": "industrial",
        "civic": "community",
        "education": "school",
        "medical": "hospital",
        "religious": "worship",
        "entertainment": "entertainment",
        "hospitality": "hotel",
        "service": "utility",
        "transportation": "utility",
    }

    # Overture Place category prefix → our building_type.
    _OVERTURE_PLACE_PREFIX_TO_TYPE: dict[str, str] = {
        "eat_and_drink": "cafe",
        "shopping": "shop",
        "education": "school",
        "health": "hospital",
        "community_and_government": "community",
        "arts_and_entertainment": "entertainment",
        "accommodation": "hotel",
        "beauty_and_spa": "shop",
        "financial_service": "office",
        "religious_organization": "worship",
    }

    def _extract_affordances(self, props: dict) -> tuple:
        """Turn any `properties["affordances"]` list (from conflation) into
        an ActivityAffordance tuple. Unknown entries are tolerated."""
        raw = props.get("affordances")
        if not isinstance(raw, list):
            return ()
        out: list[ActivityAffordance] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            activity = str(item.get("activity_type") or "visit")
            description = str(item.get("description") or item.get("name") or "")
            out.append(ActivityAffordance(
                activity_type=activity,
                description=description,
            ))
        return tuple(out)

    def _infer_floors(self, props: dict) -> int:
        """OSM building:levels → floors, falling back to Overture height."""
        levels = props.get("building:levels")
        if levels is not None:
            return self._parse_floors(str(levels))
        num_floors = props.get("overture:num_floors")
        if isinstance(num_floors, (int, float)) and num_floors >= 1:
            return max(1, int(num_floors))
        height = props.get("overture:height")
        if isinstance(height, (int, float)) and height > 0:
            # ~3m per storey is a reasonable default for this region.
            return max(1, int(round(height / 3.0)))
        return 1

    def _infer_building_type(self, props: dict) -> str:
        """Infer building functional type.

        Priority: Overture Place category > OSM amenity > OSM shop >
                  OSM building tag > Overture class > default residential.
        Overture place category wins over raw Overture class because the POI
        is the concrete activity signal ("cafe") rather than a generic zoning
        ("commercial").
        """
        # Overture Place category (set by conflation when a POI binds here)
        ov_place_cat = props.get("overture:place:category") or ""
        if ov_place_cat:
            prefix = ov_place_cat.split(".", 1)[0]
            hit = self._OVERTURE_PLACE_PREFIX_TO_TYPE.get(prefix)
            if hit:
                return hit

        # Check amenity first (most specific OSM signal)
        amenity = props.get("amenity", "")
        if amenity in _AMENITY_TO_TYPE:
            return _AMENITY_TO_TYPE[amenity]

        # Check shop
        shop = props.get("shop", "")
        if shop:
            return _SHOP_TO_TYPE.get(shop, "shop")

        # Check building tag
        building_tag = props.get("building", "")
        if building_tag in _BUILDING_TO_TYPE:
            return _BUILDING_TO_TYPE[building_tag]

        # Overture zoning class as a fallback
        ov_class = props.get("overture:class") or ""
        if ov_class in self._OVERTURE_CLASS_TO_TYPE:
            return self._OVERTURE_CLASS_TO_TYPE[ov_class]

        # building=yes with no other useful tag — assume residential
        # (most untagged buildings in suburban areas are houses)
        if building_tag == "yes":
            return "residential"

        return "residential"

    # ========== Outdoor area extraction ==========

    def _extract_outdoor_area(
        self,
        feature: dict,
        center_lat: float,
        center_lon: float,
        scale: float,
    ) -> OutdoorArea | None:
        coords = feature.get("geometry", {}).get("coordinates", [])
        if not coords:
            return None

        ring = coords[0] if isinstance(coords[0][0], list) else coords
        vertices = tuple(
            self._project(c[1], c[0], center_lat, center_lon, scale)
            for c in ring if len(c) >= 2
        )

        if len(vertices) < 3:
            return None

        props = feature.get("properties", {})
        name = props.get("name", f"area_{self._area_counter}")
        self._area_counter += 1

        area_type = self._infer_area_type(props)
        surface = props.get("surface", "grass")

        osm_tags = {}
        for key in ("leisure", "landuse", "amenity", "name", "surface"):
            if key in props:
                osm_tags[key] = str(props[key])

        return OutdoorArea(
            id=self._make_id(name, "area"),
            name=name,
            polygon=Polygon(vertices=vertices),
            area_type=area_type,
            osm_tags=osm_tags,
            surface=surface,
        )

    def _infer_area_type(self, props: dict) -> str:
        """Infer outdoor area type from OSM tags."""
        leisure = props.get("leisure", "")
        if leisure in _LEISURE_TO_AREA_TYPE:
            return _LEISURE_TO_AREA_TYPE[leisure]
        if leisure:
            return "park"

        landuse = props.get("landuse", "")
        if landuse in ("grass", "meadow", "forest"):
            return "park"
        if landuse in ("retail", "commercial"):
            return "plaza"
        if landuse == "residential":
            return "garden"

        return "park"

    # ========== Street segment extraction (核心新功能) ==========

    def _extract_street_segments(
        self,
        feature: dict,
        center_lat: float,
        center_lon: float,
        scale: float,
        segment_length: float,
    ) -> tuple[list[OutdoorArea], list[tuple[tuple[int, int], tuple[int, int]]]]:
        """
        Extract a road LineString into multiple street segment OutdoorAreas.

        Each segment is ~segment_length units long and has a polygon
        generated by buffering the line by the road width.

        Returns (segments, endpoint_keys) where endpoint_keys[i] is the
        (start_key, end_key) pair of the i-th segment, with each key being
        a rounded (lon_micro, lat_micro) integer pair derived from the raw
        OSM coordinate. Segments that share a key represent a real OSM
        intersection (same node).
        """
        coords = feature.get("geometry", {}).get("coordinates", [])
        if not coords or len(coords) < 2:
            return [], []

        props = feature.get("properties", {})
        road_name = props.get("name", f"road_{self._segment_counter}")
        highway_type = props.get("highway", "residential")
        road_width = _HIGHWAY_WIDTHS.get(highway_type, 6.0)

        # Keep raw (lon, lat) pairs in parallel with projected points so we
        # can match intersections at OSM node resolution.
        raw_coords = [(c[0], c[1]) for c in coords if len(c) >= 2]
        points = [
            self._project(c[1], c[0], center_lat, center_lon, scale)
            for c in raw_coords
        ]

        if len(points) < 2:
            return [], []

        # Split the polyline into segments of ~segment_length; carry raw
        # coord indices so we can recover the start/end OSM node for each.
        split_indices = self._split_polyline_indexed(points, segment_length)

        osm_tags = {}
        for key in ("highway", "name", "surface", "lanes", "maxspeed", "oneway"):
            if key in props:
                osm_tags[key] = str(props[key])

        surface = props.get("surface", "asphalt")
        segments: list[OutdoorArea] = []
        endpoint_keys: list[tuple[tuple[int, int], tuple[int, int]]] = []

        for i, (start_idx, end_idx) in enumerate(split_indices):
            seg_id = self._make_id(f"{road_name}_seg_{i + 1}", "seg")
            seg_name = f"{road_name} ({i + 1})"

            seg_start = points[start_idx]
            seg_end = points[end_idx]
            polygon = self._buffer_line_segment(seg_start, seg_end, road_width)

            segments.append(OutdoorArea(
                id=seg_id,
                name=seg_name,
                polygon=polygon,
                area_type="street",
                osm_tags=osm_tags,
                surface=surface,
                vegetation_density=0.0,
                road_name=road_name,
                segment_index=i,
            ))
            endpoint_keys.append((
                self._coord_key(raw_coords[start_idx]),
                self._coord_key(raw_coords[end_idx]),
            ))

            self._segment_counter += 1

        return segments, endpoint_keys

    @staticmethod
    def _coord_key(lonlat: tuple[float, float]) -> tuple[int, int]:
        """Round (lon, lat) to ~0.1m precision so shared OSM nodes collide."""
        lon, lat = lonlat
        return (int(round(lon * 1_000_000)), int(round(lat * 1_000_000)))

    def _split_polyline_indexed(
        self, points: list[Coord], segment_length: float,
    ) -> list[tuple[int, int]]:
        """Same as _split_polyline but returns vertex indices instead of Coords.

        This preserves the original polyline topology so we can map segment
        endpoints back to raw OSM coordinates.
        """
        if len(points) < 2:
            return []

        segments: list[tuple[int, int]] = []
        accumulated = 0.0
        start_idx = 0

        for i in range(1, len(points)):
            accumulated += points[i - 1].distance_to(points[i])
            if accumulated >= segment_length or i == len(points) - 1:
                segments.append((start_idx, i))
                start_idx = i
                accumulated = 0.0

        if not segments:
            segments.append((0, len(points) - 1))

        return segments

    def _buffer_line_segment(
        self, p1: Coord, p2: Coord, width: float,
    ) -> Polygon:
        """
        Create a polygon by buffering a line segment by width/2.

        Generates a rectangle around the line segment.
        """
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        length = math.sqrt(dx * dx + dy * dy)

        if length < 1e-6:
            # Degenerate segment, create a small square
            hw = width / 2
            return Polygon(vertices=(
                Coord(x=p1.x - hw, y=p1.y - hw),
                Coord(x=p1.x + hw, y=p1.y - hw),
                Coord(x=p1.x + hw, y=p1.y + hw),
                Coord(x=p1.x - hw, y=p1.y + hw),
            ))

        # Perpendicular unit vector
        nx = -dy / length * (width / 2)
        ny = dx / length * (width / 2)

        return Polygon(vertices=(
            Coord(x=p1.x + nx, y=p1.y + ny),
            Coord(x=p2.x + nx, y=p2.y + ny),
            Coord(x=p2.x - nx, y=p2.y - ny),
            Coord(x=p1.x - nx, y=p1.y - ny),
        ))

    # ========== Connection inference (自动推断连接) ==========

    def _infer_connections(
        self,
        buildings: dict[str, Building],
        outdoor_areas: dict[str, OutdoorArea],
        way_segments: list[list[str]],
        segment_endpoints: dict[str, tuple[tuple[int, int], tuple[int, int]]],
    ) -> list[Connection]:
        """
        Infer all connections between locations:
        1. Adjacent street segments within the same OSM way
        2. Intersections — segments whose raw OSM endpoints coincide (shared node)
           plus a geometric proximity fallback
        3. Building / open-space → nearest street segment within radius
        """
        connections: list[Connection] = []

        street_areas = {
            aid: area for aid, area in outdoor_areas.items()
            if area.is_street
        }

        # 1. Adjacent segments within a single OSM way
        for seg_ids in way_segments:
            for i in range(len(seg_ids) - 1):
                seg_a = outdoor_areas.get(seg_ids[i])
                seg_b = outdoor_areas.get(seg_ids[i + 1])
                if seg_a and seg_b:
                    dist = seg_a.center.distance_to(seg_b.center)
                    highway = seg_a.osm_tags.get("highway", "road")
                    connections.append(Connection(
                        from_id=seg_ids[i],
                        to_id=seg_ids[i + 1],
                        path_type=highway,
                        distance=dist,
                    ))

        conn_set: set[tuple[str, str]] = {
            tuple(sorted((c.from_id, c.to_id))) for c in connections
        }

        # 2. Intersections via shared raw OSM node at either endpoint.
        #    Two segments whose endpoint coord keys match are joined there in
        #    OSM itself — this is the ground truth, not a distance heuristic.
        endpoint_to_segs: dict[tuple[int, int], list[str]] = {}
        for seg_id, (start_key, end_key) in segment_endpoints.items():
            endpoint_to_segs.setdefault(start_key, []).append(seg_id)
            if end_key != start_key:
                endpoint_to_segs.setdefault(end_key, []).append(seg_id)

        for key, seg_ids in endpoint_to_segs.items():
            if len(seg_ids) < 2:
                continue
            seg_objs = [outdoor_areas[s] for s in seg_ids if s in outdoor_areas]
            for i in range(len(seg_objs)):
                for j in range(i + 1, len(seg_objs)):
                    a, b = seg_objs[i], seg_objs[j]
                    pair = tuple(sorted((a.id, b.id)))
                    if pair in conn_set:
                        # Already linked by adjacency within a way
                        continue
                    conn_set.add(pair)
                    connections.append(Connection(
                        from_id=a.id,
                        to_id=b.id,
                        path_type="intersection",
                        distance=a.center.distance_to(b.center),
                    ))

        # 2b. Geometric endpoint-proximity fallback. OSM often splits a single
        #    real-world junction into distinct nearby nodes (separate ways not
        #    merged at the intersection). Any two segments from DIFFERENT roads
        #    whose projected endpoints fall within PROX_M are treated as a
        #    junction. The centerline endpoints of each segment are recovered
        #    from its buffered polygon (verts 0/3 → start, verts 1/2 → end).
        PROX_M = 10.0
        endpoint_records: list[tuple[Coord, str]] = []  # (point, seg_id)
        for seg_id, seg in street_areas.items():
            verts = seg.polygon.vertices
            if len(verts) != 4:
                continue
            start = Coord(
                x=(verts[0].x + verts[3].x) / 2,
                y=(verts[0].y + verts[3].y) / 2,
            )
            end = Coord(
                x=(verts[1].x + verts[2].x) / 2,
                y=(verts[1].y + verts[2].y) / 2,
            )
            endpoint_records.append((start, seg_id))
            endpoint_records.append((end, seg_id))

        bucket = PROX_M * 2
        ep_buckets: dict[tuple[int, int], list[tuple[Coord, str]]] = {}
        for pt, sid in endpoint_records:
            k = (int(pt.x / bucket), int(pt.y / bucket))
            ep_buckets.setdefault(k, []).append((pt, sid))

        for pt, sid in endpoint_records:
            bx = int(pt.x / bucket)
            by = int(pt.y / bucket)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for other_pt, other_sid in ep_buckets.get((bx + dx, by + dy), ()):
                        if other_sid == sid:
                            continue
                        if pt.distance_to(other_pt) > PROX_M:
                            continue
                        pair = tuple(sorted((sid, other_sid)))
                        if pair in conn_set:
                            continue
                        a = street_areas[sid]
                        b = street_areas[other_sid]
                        conn_set.add(pair)
                        connections.append(Connection(
                            from_id=sid,
                            to_id=other_sid,
                            path_type="intersection",
                            distance=a.center.distance_to(b.center),
                        ))

        # 3. Connect buildings and non-street areas to the nearest street
        #    segment. Cap the radius so we don't silently invent links across
        #    disconnected street islands; isolated locations are surfaced
        #    rather than falsely joined.
        ENTRANCE_RADIUS_M = 200.0

        def _connect_to_street(loc_id: str, loc_center: Coord) -> None:
            nearest = self._find_nearest_street(loc_center, street_areas)
            if not nearest:
                return
            seg_id, dist = nearest
            if dist > ENTRANCE_RADIUS_M:
                return
            pair = tuple(sorted((loc_id, seg_id)))
            if pair in conn_set:
                return
            conn_set.add(pair)
            connections.append(Connection(
                from_id=loc_id,
                to_id=seg_id,
                path_type="entrance",
                distance=dist,
            ))

        if street_areas:
            for building in buildings.values():
                _connect_to_street(building.id, building.center)
            for area in outdoor_areas.values():
                if area.is_street:
                    continue
                _connect_to_street(area.id, area.center)

        # 4. Fallback: if no streets exist, connect nearby locations directly
        if not street_areas:
            all_locations = list(buildings.values()) + [
                a for a in outdoor_areas.values() if not a.is_street
            ]
            for i in range(len(all_locations)):
                for j in range(i + 1, len(all_locations)):
                    a, b = all_locations[i], all_locations[j]
                    dist = a.center.distance_to(b.center)
                    if dist < ENTRANCE_RADIUS_M:
                        connections.append(Connection(
                            from_id=a.id,
                            to_id=b.id,
                            path_type="path",
                            distance=dist,
                        ))

        return connections

    def _find_nearest_street(
        self, point: Coord, streets: dict[str, OutdoorArea],
    ) -> tuple[str, float] | None:
        """Find the nearest street segment to a point."""
        best_id = None
        best_dist = float("inf")

        for seg_id, seg in streets.items():
            dist = point.distance_to(seg.center)
            if dist < best_dist:
                best_dist = dist
                best_id = seg_id

        if best_id is not None:
            return best_id, best_dist
        return None

    # ========== Utility methods ==========

    def _in_bounds(self, feature: dict, bounds: dict[str, float]) -> bool:
        coords = feature.get("geometry", {}).get("coordinates", [])
        if not coords:
            return False
        flat_coords = self._flatten_coords(coords)
        for lon, lat in flat_coords:
            if (bounds["min_lat"] <= lat <= bounds["max_lat"] and
                    bounds["min_lon"] <= lon <= bounds["max_lon"]):
                return True
        return False

    def _flatten_coords(self, coords: Any) -> list[tuple[float, float]]:
        """Flatten nested coordinate arrays to list of (lon, lat)."""
        if not coords:
            return []
        if isinstance(coords[0], (int, float)):
            return [(coords[0], coords[1])] if len(coords) >= 2 else []
        if isinstance(coords[0], list) and isinstance(coords[0][0], (int, float)):
            return [(c[0], c[1]) for c in coords if len(c) >= 2]
        # Deeper nesting
        result = []
        for item in coords:
            result.extend(self._flatten_coords(item))
        return result

    def _calculate_center(self, features: list[dict]) -> tuple[float, float]:
        lats, lons = [], []
        for feature in features:
            coords = feature.get("geometry", {}).get("coordinates", [])
            flat = self._flatten_coords(coords)
            for lon, lat in flat:
                lons.append(lon)
                lats.append(lat)
        if not lats:
            return 0.0, 0.0
        return sum(lats) / len(lats), sum(lons) / len(lons)

    def _project(
        self,
        lat: float,
        lon: float,
        center_lat: float,
        center_lon: float,
        scale: float,
    ) -> Coord:
        """Project lat/lon to local meters using equirectangular approximation.

        Y axis is NEGATED so that the result is SVG-friendly (y increases downward),
        matching screen coordinates where north is up.
        """
        meters_per_deg_lat = 111320.0
        meters_per_deg_lon = 111320.0 * math.cos(math.radians(center_lat))
        return Coord(
            x=(lon - center_lon) * meters_per_deg_lon,
            y=-(lat - center_lat) * meters_per_deg_lat,  # negate for SVG y-down
        )

    def _infer_material(self, props: dict) -> Material:
        mat_str = props.get("building:material", "")
        mapping = {
            "brick": Material.BRICK,
            "wood": Material.WOOD,
            "stone": Material.STONE,
            "glass": Material.GLASS,
            "metal": Material.METAL,
            "concrete": Material.CONCRETE,
        }
        if mat_str.lower() in mapping:
            return mapping[mat_str.lower()]

        btype = props.get("building", "")
        if btype in ("house", "residential", "cabin"):
            return Material.WOOD
        if btype in ("commercial", "office"):
            return Material.GLASS
        if btype in ("church", "historic"):
            return Material.STONE

        return Material.BRICK

    @staticmethod
    def _parse_floors(raw: str) -> int:
        """Parse building:levels, handling OSM quirks like '0;1', '2.5', etc."""
        try:
            return max(1, int(float(raw.split(";")[0].strip())))
        except (ValueError, IndexError):
            return 1

    def _make_id(self, name: str, prefix: str) -> str:
        """Create a safe ID from a name, suffixing a counter on collision."""
        safe = (
            name.lower()
            .replace(" ", "_")
            .replace("'", "")
            .replace('"', "")
            .replace("/", "_")
            .replace("(", "")
            .replace(")", "")
        )
        if safe and safe not in self._used_ids:
            self._used_ids.add(safe)
            return safe
        base = safe or prefix
        n = 1
        while True:
            candidate = f"{base}_{n}"
            if candidate not in self._used_ids:
                self._used_ids.add(candidate)
                return candidate
            n += 1
