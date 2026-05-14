"""Tests for fix-realism-systemic-gaps cartography classification."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel import Atlas
from synthetic_socio_wind_tunnel.cartography.importer import GeoJSONImporter


@pytest.fixture(scope="module")
def importer() -> GeoJSONImporter:
    return GeoJSONImporter()


def test_overture_cafe_direct_lookup(importer: GeoJSONImporter) -> None:
    bt = importer._infer_building_type({
        "overture:place:category": "cafe",
        "building": "warehouse",
    })
    assert bt == "cafe", f"expected cafe got {bt}"


def test_overture_restaurant_warehouse_classified_as_restaurant(
    importer: GeoJSONImporter,
) -> None:
    bt = importer._infer_building_type({
        "overture:place:category": "restaurant",
        "building": "warehouse",
    })
    assert bt == "restaurant"


def test_overture_church_cathedral_classified_as_worship(
    importer: GeoJSONImporter,
) -> None:
    bt = importer._infer_building_type({
        "overture:place:category": "church_cathedral",
    })
    assert bt == "worship"


def test_overture_kindergarten_classified_as_school(
    importer: GeoJSONImporter,
) -> None:
    bt = importer._infer_building_type({
        "overture:place:category": "kindergarten",
    })
    assert bt == "school"


def test_unknown_overture_falls_through_to_amenity(
    importer: GeoJSONImporter,
) -> None:
    bt = importer._infer_building_type({
        "overture:place:category": "completely_unknown_category_xyz",
        "amenity": "cafe",
    })
    assert bt == "cafe"


def test_affordance_reclassifies_warehouse_to_cafe(
    importer: GeoJSONImporter,
) -> None:
    new_bt = importer._maybe_reclassify_from_affordances(
        "utility",
        [{"category": "cafe", "name": "Mowbray Eatery"}],
    )
    assert new_bt == "cafe"


def test_affordance_reclassifies_industrial_to_restaurant(
    importer: GeoJSONImporter,
) -> None:
    new_bt = importer._maybe_reclassify_from_affordances(
        "industrial",
        [{"category": "japanese_restaurant", "name": "Sake Ichiban"}],
    )
    assert new_bt == "restaurant"


def test_affordance_does_not_reclassify_existing_cafe(
    importer: GeoJSONImporter,
) -> None:
    new_bt = importer._maybe_reclassify_from_affordances(
        "cafe",
        [{"category": "restaurant", "name": "X"}],
    )
    assert new_bt == "cafe", "already-cafe should be left alone"


def test_affordance_does_not_reclassify_school(
    importer: GeoJSONImporter,
) -> None:
    new_bt = importer._maybe_reclassify_from_affordances(
        "school",
        [{"category": "cafe", "name": "X"}],
    )
    assert new_bt == "school", "specific types (school) preserved"


class TestLaneCovePOIDensity:
    """Verify the rebuilt atlas meets realism thresholds."""

    @pytest.fixture(scope="class")
    def atlas(self) -> Atlas:
        import os
        if not os.path.exists("data/lanecove_atlas.json"):
            pytest.skip("Lane Cove atlas not built yet")
        return Atlas.from_json("data/lanecove_atlas.json")

    def test_cafe_count(self, atlas: Atlas) -> None:
        n = len(atlas.list_buildings_by_type("cafe"))
        assert n >= 20, f"expected ≥ 20 cafes, got {n}"

    def test_restaurant_count(self, atlas: Atlas) -> None:
        n = len(atlas.list_buildings_by_type("restaurant"))
        assert n >= 20, f"expected ≥ 20 restaurants, got {n}"

    def test_bar_count(self, atlas: Atlas) -> None:
        n = len(atlas.list_buildings_by_type("bar"))
        assert n >= 2, f"expected ≥ 2 bars, got {n}"

    def test_residential_not_regressed(self, atlas: Atlas) -> None:
        n = len(atlas.list_residential_buildings())
        assert n >= 5000, f"residential count regressed: {n}"
