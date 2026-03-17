"""
GeoJSON Importer - Import real-world map data.

Converts GeoJSON (from OpenStreetMap, etc.) into Atlas format.
This is an OFFLINE tool - run before game starts.
"""

from __future__ import annotations
import json
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
)


class GeoJSONImporter:
    """
    Import GeoJSON data into Atlas format.

    Workflow:
    1. Load GeoJSON (from OpenStreetMap, etc.)
    2. Filter by bounds if needed
    3. Extract buildings and areas
    4. Infer connections from roads
    5. Output Atlas-compatible Region

    Example:
        importer = GeoJSONImporter()
        region = importer.import_file("town.geojson", scale=10000)
        region.model_dump()  # Save as atlas.json
    """

    def __init__(self):
        self._building_counter = 0
        self._area_counter = 0

    def import_file(
        self,
        path: str | Path,
        bounds: dict[str, float] | None = None,
        scale: float = 10000.0,
        region_id: str = "imported",
    ) -> Region:
        """
        Import GeoJSON file.

        Args:
            path: Path to GeoJSON file
            bounds: Optional crop bounds {min_lat, max_lat, min_lon, max_lon}
            scale: Coordinate scale factor
            region_id: ID for the output region

        Returns:
            Region ready for Atlas
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self.import_data(data, bounds, scale, region_id)

    def import_data(
        self,
        geojson: dict[str, Any],
        bounds: dict[str, float] | None = None,
        scale: float = 10000.0,
        region_id: str = "imported",
    ) -> Region:
        """Import from GeoJSON dictionary."""
        features = geojson.get("features", [])

        if bounds:
            features = [f for f in features if self._in_bounds(f, bounds)]

        center_lat, center_lon = self._calculate_center(features)

        buildings: dict[str, Building] = {}
        outdoor_areas: dict[str, OutdoorArea] = {}

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

        # Calculate bounds
        all_coords = []
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

        return Region(
            id=region_id,
            name=region_id.replace("_", " ").title(),
            bounds_min=bounds_min,
            bounds_max=bounds_max,
            buildings=buildings,
            outdoor_areas=outdoor_areas,
            connections=(),
        )

    def _in_bounds(self, feature: dict, bounds: dict[str, float]) -> bool:
        coords = feature.get("geometry", {}).get("coordinates", [])
        if not coords:
            return False
        if isinstance(coords[0][0], list):
            coords = coords[0]
        for lon, lat in coords:
            if (bounds["min_lat"] <= lat <= bounds["max_lat"] and
                bounds["min_lon"] <= lon <= bounds["max_lon"]):
                return True
        return False

    def _calculate_center(self, features: list[dict]) -> tuple[float, float]:
        lats, lons = [], []
        for feature in features:
            coords = feature.get("geometry", {}).get("coordinates", [])
            if not coords:
                continue
            if isinstance(coords[0], list):
                if isinstance(coords[0][0], list):
                    coords = coords[0]
                for coord in coords:
                    if len(coord) >= 2:
                        lons.append(coord[0])
                        lats.append(coord[1])
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
        return Coord(
            x=(lon - center_lon) * scale,
            y=(lat - center_lat) * scale,
        )

    def _is_building(self, props: dict) -> bool:
        return "building" in props

    def _is_area(self, props: dict) -> bool:
        return any(k in props for k in ["leisure", "landuse", "amenity"])

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
        name = props.get("name", f"building_{self._building_counter}")
        self._building_counter += 1

        polygon = Polygon(vertices=vertices)
        material = self._infer_material(props)

        return Building(
            id=name.lower().replace(" ", "_").replace("'", ""),
            name=name,
            polygon=polygon,
            exterior_material=material,
            floors=int(props.get("building:levels", 1)),
            entrance_coord=polygon.center,
        )

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

        surface = props.get("surface", "grass")

        return OutdoorArea(
            id=name.lower().replace(" ", "_").replace("'", ""),
            name=name,
            polygon=Polygon(vertices=vertices),
            surface=surface,
        )

    def _infer_material(self, props: dict) -> Material:
        mat_str = props.get("building:material", "")
        mapping = {
            "brick": Material.BRICK,
            "wood": Material.WOOD,
            "stone": Material.STONE,
            "glass": Material.GLASS,
            "metal": Material.METAL,
        }
        if mat_str.lower() in mapping:
            return mapping[mat_str.lower()]

        btype = props.get("building", "")
        if btype in ["house", "residential", "cabin"]:
            return Material.WOOD
        if btype in ["commercial", "office"]:
            return Material.GLASS
        if btype in ["church", "historic"]:
            return Material.STONE

        return Material.BRICK
