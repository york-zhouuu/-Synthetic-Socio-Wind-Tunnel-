"""A3 / realism-poi-capacity: POIHeatModel tests."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.atlas.heat import (
    POIHeatModel,
    default_capacity_for_area_type,
)


@pytest.fixture
def atlas_fake():
    """Minimal fake atlas for heat tests."""
    class FakeArea:
        def __init__(self, area_id: str, capacity: int | None) -> None:
            self.id = area_id
            self.capacity = capacity

    class FakeAtlas:
        def __init__(self) -> None:
            self._areas = {
                "cafe_main": FakeArea("cafe_main", 5),
                "park_lc": FakeArea("park_lc", None),
                "shop_a": FakeArea("shop_a", 2),
            }

        def get_outdoor_area(self, aid: str):
            return self._areas.get(aid)

        def get_building(self, bid: str):
            return None

    return FakeAtlas()


class TestArrivalDeparture:

    def test_arrival_increments(self, atlas_fake):
        m = POIHeatModel.from_atlas(atlas_fake)
        for i in range(3):
            m.register_arrival("cafe_main", f"a{i}")
        assert m.current_occupancy("cafe_main") == 3

    def test_idempotent_arrival(self, atlas_fake):
        m = POIHeatModel.from_atlas(atlas_fake)
        m.register_arrival("cafe_main", "a1")
        m.register_arrival("cafe_main", "a1")
        assert m.current_occupancy("cafe_main") == 1

    def test_arrival_moves_from_previous_loc(self, atlas_fake):
        m = POIHeatModel.from_atlas(atlas_fake)
        m.register_arrival("cafe_main", "a1")
        m.register_arrival("park_lc", "a1")
        assert m.current_occupancy("cafe_main") == 0
        assert m.current_occupancy("park_lc") == 1

    def test_departure_decrements(self, atlas_fake):
        m = POIHeatModel.from_atlas(atlas_fake)
        m.register_arrival("cafe_main", "a1")
        m.register_departure("cafe_main", "a1")
        assert m.current_occupancy("cafe_main") == 0


class TestIsFull:

    def test_below_capacity_not_full(self, atlas_fake):
        m = POIHeatModel.from_atlas(atlas_fake)
        for i in range(3):
            m.register_arrival("cafe_main", f"a{i}")
        assert not m.is_full("cafe_main")

    def test_at_capacity_full(self, atlas_fake):
        m = POIHeatModel.from_atlas(atlas_fake)
        for i in range(5):
            m.register_arrival("cafe_main", f"a{i}")
        assert m.is_full("cafe_main")

    def test_unbounded_never_full(self, atlas_fake):
        m = POIHeatModel.from_atlas(atlas_fake)
        for i in range(1000):
            m.register_arrival("park_lc", f"a{i}")
        assert not m.is_full("park_lc")

    def test_unknown_location_not_full(self, atlas_fake):
        m = POIHeatModel.from_atlas(atlas_fake)
        assert not m.is_full("nonexistent_xyz")


class TestDefaults:

    def test_cafe_has_default(self):
        assert default_capacity_for_area_type("cafe") == 15

    def test_park_unbounded(self):
        assert default_capacity_for_area_type("park") is None

    def test_unknown_type_unbounded(self):
        assert default_capacity_for_area_type("nonsense") is None
