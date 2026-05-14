"""Tests for typed atlas accessors used by location_pools (cartography spec)."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel import Atlas


@pytest.fixture(scope="module")
def lc_atlas() -> Atlas:
    return Atlas.from_json("data/lanecove_atlas.json")


def test_list_workplaces_returns_workplace_types_only(lc_atlas: Atlas) -> None:
    wp = lc_atlas.list_workplaces()
    assert wp, "Lane Cove atlas should have at least one workplace"

    valid_types = {"commercial", "community", "hospital", "office", "school"}
    for b in wp:
        assert b.building_type in valid_types, (
            f"unexpected workplace type {b.building_type} on {b.id}"
        )
        assert b.building_type != "residential", (
            f"residential {b.id} leaked into workplaces"
        )


def test_list_pois_returns_four_categories(lc_atlas: Atlas) -> None:
    pois = lc_atlas.list_pois()
    assert set(pois.keys()) == {"food_drink", "shop", "leisure", "civic"}

    for cat, items in pois.items():
        assert items, f"category {cat} should not be empty on Lane Cove atlas"


def test_pois_leisure_mixes_buildings_and_outdoor(lc_atlas: Atlas) -> None:
    leisure = lc_atlas.list_pois()["leisure"]
    has_building = any(hasattr(o, "building_type") for o in leisure)
    has_outdoor = any(hasattr(o, "area_type") for o in leisure)
    assert has_building, "leisure should include at least one building"
    assert has_outdoor, "leisure should include at least one outdoor area"


def test_residential_disjoint_from_workplaces_and_pois(lc_atlas: Atlas) -> None:
    residential_ids = {b.id for b in lc_atlas.list_residential_buildings()}
    workplace_ids = {b.id for b in lc_atlas.list_workplaces()}

    overlap = residential_ids & workplace_ids
    assert not overlap, f"residential leaked into workplaces: {overlap}"

    pois = lc_atlas.list_pois()
    for cat in ("food_drink", "shop", "leisure", "civic"):
        cat_ids = {getattr(o, "id") for o in pois[cat]}
        overlap = residential_ids & cat_ids
        assert not overlap, (
            f"residential leaked into pois.{cat}: {overlap}"
        )


def test_accessors_deterministic_and_ordered(lc_atlas: Atlas) -> None:
    wp1 = [b.id for b in lc_atlas.list_workplaces()]
    wp2 = [b.id for b in lc_atlas.list_workplaces()]
    assert wp1 == wp2, "list_workplaces not deterministic"
    assert wp1 == sorted(wp1), "list_workplaces not sorted by id"

    pois1 = lc_atlas.list_pois()
    pois2 = lc_atlas.list_pois()
    for cat in pois1:
        ids1 = [getattr(o, "id") for o in pois1[cat]]
        ids2 = [getattr(o, "id") for o in pois2[cat]]
        assert ids1 == ids2, f"list_pois.{cat} not deterministic"
        assert ids1 == sorted(ids1), f"list_pois.{cat} not sorted by id"


def test_list_buildings_by_type_sorted(lc_atlas: Atlas) -> None:
    cafes = [b.id for b in lc_atlas.list_buildings_by_type("cafe")]
    assert cafes == sorted(cafes), "list_buildings_by_type not sorted"
