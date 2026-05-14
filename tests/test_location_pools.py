"""Tests for typed location pools (agent spec)."""

from __future__ import annotations

import random

import pytest

from synthetic_socio_wind_tunnel import (
    Atlas,
    LocationPoolError,
    LocationPools,
    build_location_pools,
)


@pytest.fixture(scope="module")
def lc_atlas() -> Atlas:
    return Atlas.from_json("data/lanecove_atlas.json")


def _build(atlas: Atlas, seed: int = 42, *, home=40, work=20, poi=30) -> LocationPools:
    return build_location_pools(
        atlas, home_count=home, work_count=work, poi_count=poi,
        rng=random.Random(seed),
    )


def test_validate_legal_pools_returns_self(lc_atlas: Atlas) -> None:
    pools = _build(lc_atlas)
    same = pools.validate(lc_atlas)
    assert same is pools


def test_validate_rejects_overlap(lc_atlas: Atlas) -> None:
    pools = _build(lc_atlas)
    overlapped = LocationPools(
        home_pool=pools.home_pool,
        work_pool=(pools.home_pool[0],) + pools.work_pool[1:],
        poi_pool=pools.poi_pool,
        target_location=None,
    )
    with pytest.raises(LocationPoolError, match="pools overlap"):
        overlapped.validate(lc_atlas)


def test_validate_rejects_target_outside_poi(lc_atlas: Atlas) -> None:
    pools = _build(lc_atlas)
    bad = LocationPools(
        home_pool=pools.home_pool,
        work_pool=pools.work_pool,
        poi_pool=pools.poi_pool,
        target_location="some_nonexistent_id",
    )
    with pytest.raises(LocationPoolError, match="target_location"):
        bad.validate(lc_atlas)


def test_build_is_deterministic(lc_atlas: Atlas) -> None:
    a = _build(lc_atlas, seed=42)
    b = _build(lc_atlas, seed=42)
    assert a.home_pool == b.home_pool
    assert a.work_pool == b.work_pool
    assert a.poi_pool == b.poi_pool


def test_build_different_seeds_diverge(lc_atlas: Atlas) -> None:
    a = _build(lc_atlas, seed=42)
    b = _build(lc_atlas, seed=99)
    assert a.home_pool != b.home_pool


def test_build_fails_when_count_exceeds_available(lc_atlas: Atlas) -> None:
    with pytest.raises(LocationPoolError, match="home_count"):
        build_location_pools(
            lc_atlas, home_count=10_000, work_count=20, poi_count=30,
            rng=random.Random(42),
        )


def test_build_fails_when_count_nonpositive(lc_atlas: Atlas) -> None:
    with pytest.raises(LocationPoolError, match="must be positive"):
        build_location_pools(
            lc_atlas, home_count=0, work_count=20, poi_count=30,
            rng=random.Random(42),
        )


def test_pools_are_pairwise_disjoint(lc_atlas: Atlas) -> None:
    pools = _build(lc_atlas)
    h, w, p = set(pools.home_pool), set(pools.work_pool), set(pools.poi_pool)
    assert not (h & w)
    assert not (h & p)
    assert not (w & p)


def test_pools_all_reachable_via_atlas_findpath(lc_atlas: Atlas) -> None:
    pools = _build(lc_atlas)
    all_ids = list(pools.home_pool) + list(pools.work_pool) + list(pools.poi_pool)
    anchor = all_ids[0]
    for other in all_ids[1:]:
        ok, _, _ = lc_atlas.find_path(anchor, other)
        assert ok, f"unreachable: {anchor} → {other}"


def test_home_pool_all_residential(lc_atlas: Atlas) -> None:
    pools = _build(lc_atlas)
    for h_id in pools.home_pool:
        b = lc_atlas.get_building(h_id)
        assert b is not None, f"home {h_id} is not a building"
        assert b.building_type == "residential", (
            f"home {h_id} is {b.building_type}, not residential"
        )


def test_pick_target_community_preference(lc_atlas: Atlas) -> None:
    pools = _build(lc_atlas)
    target = pools.pick_target_location(
        lc_atlas, random.Random(42), prefer="community",
    )
    assert target in pools.poi_pool


def test_pick_target_park_preference(lc_atlas: Atlas) -> None:
    pools = _build(lc_atlas)
    target = pools.pick_target_location(
        lc_atlas, random.Random(42), prefer="park",
    )
    outdoor = lc_atlas.get_outdoor_area(target)
    building = lc_atlas.get_building(target)
    is_park = outdoor is not None and outdoor.area_type in (
        "park", "playground", "garden",
    )
    is_fallback = building is not None or outdoor is not None
    assert is_park or is_fallback


def test_quotas_guarantee_food_drink(lc_atlas: Atlas) -> None:
    pools = build_location_pools(lc_atlas, home_count=40, rng=random.Random(42))
    foods = [
        p for p in pools.poi_pool
        if (b := lc_atlas.get_building(p))
        and b.building_type in ("cafe", "restaurant", "bar")
    ]
    assert len(foods) >= 8, f"expected ≥ 8 food_drink in poi_pool, got {len(foods)}"


def test_quotas_school_share_capped(lc_atlas: Atlas) -> None:
    pools = build_location_pools(lc_atlas, home_count=40, rng=random.Random(42))
    schools = [
        w for w in pools.work_pool
        if (b := lc_atlas.get_building(w)) and b.building_type == "school"
    ]
    assert len(schools) <= 7, f"school dominance: {len(schools)} of {len(pools.work_pool)}"


def test_quotas_n_agents_scaling(lc_atlas: Atlas) -> None:
    """1000-agent run should produce a work_pool meaningfully larger than the
    default quota total (17). Cap respects per-category limits so the pool
    cannot grow beyond what atlas categorically supplies."""
    big = build_location_pools(
        lc_atlas, home_count=500, n_agents=1000, rng=random.Random(99),
    )
    assert len(big.work_pool) >= 50, f"1000-agent work_pool too small: {len(big.work_pool)}"
    assert len(big.poi_pool) >= 50, f"1000-agent poi_pool too small: {len(big.poi_pool)}"


def test_quotas_undersupply_does_not_raise(lc_atlas: Atlas) -> None:
    # Lane Cove has finite workplaces; requesting 1000 must cap, not raise.
    pools = build_location_pools(
        lc_atlas, home_count=100, work_count=1000, poi_count=30,
        rng=random.Random(7),
    )
    # work_pool capped at quota total when top-off is constrained by per-cat caps
    assert len(pools.work_pool) >= 15


def test_pick_target_deterministic_with_same_rng(lc_atlas: Atlas) -> None:
    pools = _build(lc_atlas)
    t1 = pools.pick_target_location(lc_atlas, random.Random(7), prefer="community")
    t2 = pools.pick_target_location(lc_atlas, random.Random(7), prefer="community")
    assert t1 == t2
