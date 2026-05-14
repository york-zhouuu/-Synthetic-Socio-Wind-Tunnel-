"""Tests for perception-gated destination-swap helper (A1 / realism-perception-loop)."""

from __future__ import annotations

import random
from types import SimpleNamespace

from synthetic_socio_wind_tunnel.agent.scripted_plan import (
    perception_gated_destination_swap,
)
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.perception.models import (
    EntitySnapshot,
    SubjectiveView,
)


class _FakeArea:
    def __init__(self, x: float, y: float, area_type: str = "cafe") -> None:
        self.center = Coord(x=x, y=y)
        self.area_type = area_type


class _FakeAtlas:
    def __init__(self, areas: dict[str, _FakeArea]) -> None:
        self._areas = areas

    def list_outdoor_areas(self) -> list[str]:
        return list(self._areas.keys())

    def get_outdoor_area(self, aid: str) -> _FakeArea | None:
        return self._areas.get(aid)


def _step(destination: str = "cafe_main"):
    return SimpleNamespace(destination=destination)


def _crowded_view(n: int = 6) -> SubjectiveView:
    return SubjectiveView(
        observer_id="obs",
        location_id="cafe_main",
        location_name="Cafe Main",
        entity_snapshots=[
            EntitySnapshot(entity_id=f"a_{i}", location_id="cafe_main")
            for i in range(n)
        ],
    )


def _empty_view() -> SubjectiveView:
    return SubjectiveView(
        observer_id="obs",
        location_id="cafe_main",
        location_name="Cafe Main",
    )


def _atlas_with_alts(num_alts: int = 3) -> _FakeAtlas:
    areas = {"cafe_main": _FakeArea(0, 0, "cafe")}
    for i in range(num_alts):
        # Place each at increasing distance < 1000m
        areas[f"cafe_alt_{i}"] = _FakeArea((i + 1) * 100, 0, "cafe")
    return _FakeAtlas(areas)


class TestSwapTriggers:

    def test_high_openness_crowded_swaps(self):
        """High openness + crowded → very likely swap."""
        atlas = _atlas_with_alts()
        # Use seeded rng. With openness=1.0, p_swap=0.5 → roughly 50% swap rate.
        # Test: at least 30 swaps in 100 trials.
        swap_count = 0
        for seed in range(100):
            rng = random.Random(seed)
            result = perception_gated_destination_swap(
                current_step=_step(),
                perceptual_view=_crowded_view(6),
                rng=rng,
                atlas=atlas,
                openness=1.0,
                crowd_threshold=5,
            )
            if result is not None:
                swap_count += 1
        assert swap_count >= 30, f"高 openness 时 swap 太少: {swap_count}/100"

    def test_low_openness_rarely_swaps(self):
        atlas = _atlas_with_alts()
        swap_count = 0
        for seed in range(100):
            rng = random.Random(seed)
            result = perception_gated_destination_swap(
                current_step=_step(),
                perceptual_view=_crowded_view(6),
                rng=rng,
                atlas=atlas,
                openness=0.1,
                crowd_threshold=5,
            )
            if result is not None:
                swap_count += 1
        assert swap_count <= 15, f"低 openness 时 swap 太多: {swap_count}/100"


class TestNoSwapConditions:

    def test_not_crowded_no_swap(self):
        atlas = _atlas_with_alts()
        rng = random.Random(42)
        result = perception_gated_destination_swap(
            current_step=_step(),
            perceptual_view=_crowded_view(2),  # below threshold
            rng=rng,
            atlas=atlas,
            openness=1.0,
            crowd_threshold=5,
        )
        assert result is None

    def test_no_view_no_swap(self):
        atlas = _atlas_with_alts()
        rng = random.Random(42)
        result = perception_gated_destination_swap(
            current_step=_step(),
            perceptual_view=None,
            rng=rng,
            atlas=atlas,
            openness=1.0,
        )
        assert result is None

    def test_no_alternatives_no_swap(self):
        """Atlas has no alternatives → returns None."""
        atlas = _FakeAtlas({"cafe_main": _FakeArea(0, 0, "cafe")})
        rng = random.Random(42)
        result = perception_gated_destination_swap(
            current_step=_step(),
            perceptual_view=_crowded_view(6),
            rng=rng,
            atlas=atlas,
            openness=1.0,
            crowd_threshold=5,
        )
        assert result is None


class TestSelectionRules:

    def test_picks_same_area_type(self):
        """If all candidates are same type, picks one of them."""
        atlas = _atlas_with_alts(num_alts=3)
        # Force swap by exhaustive seeds
        for seed in range(50):
            rng = random.Random(seed)
            result = perception_gated_destination_swap(
                current_step=_step(),
                perceptual_view=_crowded_view(6),
                rng=rng,
                atlas=atlas,
                openness=1.0,
                crowd_threshold=5,
            )
            if result is not None:
                assert result.startswith("cafe_alt_")
                assert atlas.get_outdoor_area(result).area_type == "cafe"
                return
        assert False, "50 seeds 都没 swap，统计意义异常"

    def test_excludes_different_area_type(self):
        atlas = _FakeAtlas({
            "cafe_main": _FakeArea(0, 0, "cafe"),
            "park_far": _FakeArea(100, 0, "park"),  # different type
        })
        rng = random.Random(42)
        result = perception_gated_destination_swap(
            current_step=_step(),
            perceptual_view=_crowded_view(6),
            rng=rng,
            atlas=atlas,
            openness=1.0,
            crowd_threshold=5,
        )
        # No same-type alternative → None
        assert result is None

    def test_excludes_far_areas(self):
        """Areas > 1000m away SHALL not be selected."""
        atlas = _FakeAtlas({
            "cafe_main": _FakeArea(0, 0, "cafe"),
            "cafe_too_far": _FakeArea(2000, 0, "cafe"),
        })
        rng = random.Random(42)
        result = perception_gated_destination_swap(
            current_step=_step(),
            perceptual_view=_crowded_view(6),
            rng=rng,
            atlas=atlas,
            openness=1.0,
            crowd_threshold=5,
        )
        assert result is None
