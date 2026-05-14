"""Typed location pools for agent population init and scripted plans.

Replaces the old `_pick_connected_destinations` single-pool sampler that only
drew from outdoor_areas. The bug led to agent.home_location being a street
segment, scripted_plan destinations being all streets, and 0% dwell inside
residential/cafe/shop buildings (see openspec change
`fix-population-uses-typed-locations` for the full bug trace).

Three disjoint pools:
- home_pool: residential buildings (agent.home_location source)
- work_pool: office/school/commercial/community/hospital buildings
- poi_pool: cafe/restaurant/shop/bar/entertainment/hotel/worship buildings
  plus park/playground/garden outdoor areas (scripted_plan errand/leisure)

All pools live in a single atlas connection-graph connected component, so
NavigationService can route between any two pool members.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas


class LocationPoolError(Exception):
    """Raised when typed pool construction or validation fails."""


_DEFAULT_WORK_QUOTAS: dict[str, int] = {
    "office": 4, "school": 6, "commercial": 4,
    "community": 2, "hospital": 1,
}
_DEFAULT_POI_QUOTAS: dict[str, int] = {
    "food_drink": 8, "shop": 6,
    "leisure_building": 4, "leisure_outdoor": 12,
}

# Building types per POI quota category
_POI_CATEGORY_TO_BUILDING_TYPES: dict[str, tuple[str, ...]] = {
    "food_drink": ("cafe", "restaurant", "bar"),
    "shop": ("shop",),
    "leisure_building": ("entertainment", "hotel", "worship"),
}
_POI_CATEGORY_OUTDOOR_TYPES: dict[str, tuple[str, ...]] = {
    "leisure_outdoor": ("park", "playground", "garden"),
}


@dataclass(frozen=True)
class PoolQuotas:
    """Per-category minimum counts for work_pool and poi_pool sampling.

    fix-realism-systemic-gaps: replaces "single random.sample from combined
    pool" with per-type quotas so cafe / restaurant aren't crowded out by
    parks/playgrounds, and school doesn't dominate workplaces.
    """
    work: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_WORK_QUOTAS))
    poi: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_POI_QUOTAS))

    def total_work(self) -> int:
        return sum(self.work.values())

    def total_poi(self) -> int:
        return sum(self.poi.values())


@dataclass(frozen=True)
class LocationPools:
    """Typed destination pools used by population/scripted_plan/variant push.

    All four fields hold location_ids referring to atlas buildings or
    outdoor_areas. The three pools (home/work/poi) MUST be pairwise disjoint
    and reachable within the same atlas connection-graph component.
    """

    home_pool: tuple[str, ...]
    work_pool: tuple[str, ...]
    poi_pool: tuple[str, ...]
    target_location: str | None

    def validate(self, atlas: "Atlas") -> "LocationPools":
        """Assert disjointness, target membership, and reachability.

        Returns self on success; raises LocationPoolError on failure.
        """
        h = set(self.home_pool)
        w = set(self.work_pool)
        p = set(self.poi_pool)

        if h & w:
            raise LocationPoolError(
                f"pools overlap: home ∩ work = {sorted(h & w)[:5]}"
            )
        if h & p:
            raise LocationPoolError(
                f"pools overlap: home ∩ poi = {sorted(h & p)[:5]}"
            )
        if w & p:
            raise LocationPoolError(
                f"pools overlap: work ∩ poi = {sorted(w & p)[:5]}"
            )

        if self.target_location is not None and self.target_location not in p:
            raise LocationPoolError(
                f"target_location {self.target_location!r} not in poi_pool"
            )

        all_ids = list(self.home_pool) + list(self.work_pool) + list(self.poi_pool)
        if all_ids:
            anchor = all_ids[0]
            for other in all_ids[1:]:
                ok, _, _ = atlas.find_path(anchor, other)
                if not ok:
                    raise LocationPoolError(
                        f"location {other!r} not reachable from {anchor!r}"
                    )
        return self

    _COMMUNITY_PREF_TYPES = ("community", "worship")
    _CAFE_PREF_TYPES = ("cafe", "restaurant")
    _PARK_PREF_AREA_TYPES = ("park", "playground", "garden")

    def pick_target_location(
        self,
        atlas: "Atlas",
        rng: random.Random,
        prefer: str = "community",
    ) -> str:
        """Pick a variant push target from poi_pool by preference order.

        Preference cascade: community → cafe → park → poi_pool[0].
        `prefer` toggles which group is searched first.
        """
        if not self.poi_pool:
            raise LocationPoolError("poi_pool empty; cannot pick target")

        cascade: list[tuple[str, ...]] = []
        if prefer == "cafe":
            cascade = [self._CAFE_PREF_TYPES, self._COMMUNITY_PREF_TYPES,
                       self._PARK_PREF_AREA_TYPES]
        elif prefer == "park":
            cascade = [self._PARK_PREF_AREA_TYPES, self._COMMUNITY_PREF_TYPES,
                       self._CAFE_PREF_TYPES]
        else:  # community (default)
            cascade = [self._COMMUNITY_PREF_TYPES, self._CAFE_PREF_TYPES,
                       self._PARK_PREF_AREA_TYPES]

        for group in cascade:
            candidates = []
            for loc_id in self.poi_pool:
                building = atlas.get_building(loc_id)
                if building is not None and building.building_type in group:
                    candidates.append(loc_id)
                    continue
                outdoor = atlas.get_outdoor_area(loc_id)
                if outdoor is not None and outdoor.area_type in group:
                    candidates.append(loc_id)
            if candidates:
                return rng.choice(sorted(candidates))

        return self.poi_pool[0]


def _candidate_ids_from_buildings(buildings: Iterable, atlas: "Atlas") -> list[str]:
    """Filter buildings to those reachable through the atlas connection graph."""
    return [
        b.id for b in buildings
        if b.id in atlas._connection_graph  # noqa: SLF001 — adjacency probe
    ]


def _candidate_outdoor_ids(area_types: Iterable[str], atlas: "Atlas") -> list[str]:
    types = set(area_types)
    return sorted(
        a.id for a in atlas.region.outdoor_areas.values()
        if a.area_type in types and a.id in atlas._connection_graph  # noqa: SLF001
    )


def _largest_connected_component(atlas: "Atlas", anchors: list[str]) -> set[str]:
    """BFS from each anchor, return the largest component found."""
    largest: set[str] = set()
    seen_starts: set[str] = set()
    for anchor in anchors:
        if anchor in seen_starts:
            continue
        component: set[str] = {anchor}
        queue = [anchor]
        while queue:
            current = queue.pop(0)
            for neighbor, _ in atlas.get_connections(current):
                if neighbor not in component:
                    component.add(neighbor)
                    queue.append(neighbor)
        seen_starts |= component
        if len(component) > len(largest):
            largest = component
    return largest


def _sample_with_quotas(
    quotas: dict[str, int],
    candidates_by_category: dict[str, list[str]],
    *,
    fallback_pool: list[str],
    target_count: int,
    rng: random.Random,
) -> list[str]:
    """Sample per-category quotas, top off to target_count from leftovers.

    Each category draws min(quota, len(candidates)) entries. Top-off SHALL
    NOT exceed any category's quota — Lane Cove atlas has 91 schools, so a
    naive top-off would let schools dominate. Top-off draws only from
    categories already at quota: prefers no specific direction, rotates by
    rng.shuffle.
    """
    import sys
    picked: list[str] = []
    used: set[str] = set()
    # Map every candidate to its (single) category for cap enforcement
    cat_of: dict[str, str] = {}
    for category, cands in candidates_by_category.items():
        for c in cands:
            cat_of.setdefault(c, category)

    for category, quota in quotas.items():
        cands = [c for c in candidates_by_category.get(category, [])
                 if c not in used]
        take = min(quota, len(cands))
        if take < quota:
            print(
                f"[location_pools] warning: category {category!r} quota={quota} "
                f"but only {len(cands)} candidates available; topping off later",
                file=sys.stderr,
            )
        if take > 0:
            chosen = rng.sample(cands, take)
            picked.extend(chosen)
            used.update(chosen)

    # Top off to target_count. Quotas are MINIMUMS; cap per category at
    # max(2 × quota, target_count // num_categories) so no single category
    # dominates but the pool can scale with target_count (e.g. 1000-agent run
    # wants ~200 workplaces; 5 categories × 40 cap each = 200 capacity).
    remaining = target_count - len(picked)
    if remaining > 0:
        n_cats = max(1, len(quotas))
        per_cat_cap: dict[str, int] = {
            cat: max(2 * quota, target_count // n_cats)
            for cat, quota in quotas.items()
        }
        cat_counts: dict[str, int] = {}
        for p in picked:
            c = cat_of.get(p)
            if c:
                cat_counts[c] = cat_counts.get(c, 0) + 1

        leftover = [c for c in fallback_pool if c not in used]
        rng.shuffle(leftover)
        for c in leftover:
            if remaining <= 0:
                break
            cat = cat_of.get(c)
            if cat is not None:
                cap = per_cat_cap.get(cat, 0)
                if cat_counts.get(cat, 0) >= cap:
                    continue
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
            picked.append(c)
            used.add(c)
            remaining -= 1
    return picked


def build_location_pools(
    atlas: "Atlas",
    *,
    home_count: int,
    work_count: int | None = None,
    poi_count: int | None = None,
    quotas: PoolQuotas | None = None,
    n_agents: int | None = None,
    rng: random.Random,
) -> LocationPools:
    """Sample three disjoint typed pools all reachable in one component.

    fix-realism-systemic-gaps: pools now respect per-type quotas so
    food_drink / shop / leisure / civic are guaranteed minimums. Pool sizes
    scale with n_agents when explicit counts are omitted, so 1000-agent runs
    don't squeeze 1000 agents into 20 workplaces.

    Raises LocationPoolError if any pool is undersupplied or disjointness
    cannot be achieved within 5 retries.
    """
    if home_count <= 0:
        raise LocationPoolError(f"home_count must be positive; got {home_count}")
    if quotas is None:
        quotas = PoolQuotas()
    # Derive default counts: respect explicit overrides, else use quota total,
    # scaled up by n_agents when given.
    if work_count is None:
        work_count = quotas.total_work()
        if n_agents is not None:
            work_count = max(work_count, n_agents // 5)
    if poi_count is None:
        poi_count = quotas.total_poi()
        if n_agents is not None:
            poi_count = max(poi_count, n_agents // 5)
    if work_count <= 0 or poi_count <= 0:
        raise LocationPoolError(
            f"counts must be positive; got home={home_count} "
            f"work={work_count} poi={poi_count}"
        )

    home_all = _candidate_ids_from_buildings(
        atlas.list_residential_buildings(), atlas,
    )
    work_all = _candidate_ids_from_buildings(atlas.list_workplaces(), atlas)

    poi_groups = atlas.list_pois()
    poi_building_ids: list[str] = []
    for category in ("food_drink", "shop", "leisure"):
        for item in poi_groups.get(category, []):
            if not hasattr(item, "building_type"):
                continue
            if item.id in atlas._connection_graph:  # noqa: SLF001
                poi_building_ids.append(item.id)
    poi_outdoor_ids = _candidate_outdoor_ids(
        ("park", "playground", "garden"), atlas,
    )
    poi_all = sorted(set(poi_building_ids) | set(poi_outdoor_ids))

    if len(home_all) < home_count:
        raise LocationPoolError(
            f"home_count={home_count} exceeds available {len(home_all)} "
            f"residential buildings"
        )
    # fix-realism-systemic-gaps: cap pool sizes at atlas availability instead
    # of raising; small suburbs have finite POI density.
    if len(work_all) < work_count:
        import sys
        print(
            f"[location_pools] note: requested work_count={work_count} > "
            f"{len(work_all)} available workplaces; capping to atlas reality",
            file=sys.stderr,
        )
        work_count = len(work_all)
    if len(poi_all) < poi_count:
        import sys
        print(
            f"[location_pools] note: requested poi_count={poi_count} > "
            f"{len(poi_all)} available POIs; capping to atlas reality",
            file=sys.stderr,
        )
        poi_count = len(poi_all)

    component = _largest_connected_component(
        atlas, [home_all[0], work_all[0], poi_all[0]],
    )
    home_in = [h for h in home_all if h in component]
    work_in = [w for w in work_all if w in component]
    poi_in = [p for p in poi_all if p in component]

    if len(home_in) < home_count:
        raise LocationPoolError(
            f"home_count={home_count} exceeds {len(home_in)} residential "
            f"buildings in main connected component (total residential "
            f"available={len(home_all)})"
        )
    # fix-realism-systemic-gaps: cap pool sizes at availability instead of
    # raising — small suburbs (Lane Cove ~160 workplaces) genuinely have
    # finite POI density, so 1000-agent runs share workplaces.
    if work_count > len(work_in):
        import sys
        print(
            f"[location_pools] note: requested work_count={work_count} > "
            f"{len(work_in)} available workplaces; capping to atlas reality",
            file=sys.stderr,
        )
        work_count = len(work_in)
    if poi_count > len(poi_in):
        import sys
        print(
            f"[location_pools] note: requested poi_count={poi_count} > "
            f"{len(poi_in)} available POIs; capping to atlas reality",
            file=sys.stderr,
        )
        poi_count = len(poi_in)

    # Build per-category candidate sub-pools (filtered to the connected component)
    work_by_type: dict[str, list[str]] = {}
    for wid in work_in:
        b = atlas.get_building(wid)
        if b is None: continue
        work_by_type.setdefault(b.building_type, []).append(wid)
    poi_by_category: dict[str, list[str]] = {
        "food_drink": [], "shop": [], "leisure_building": [],
        "leisure_outdoor": [],
    }
    for pid in poi_in:
        b = atlas.get_building(pid)
        o = atlas.get_outdoor_area(pid)
        if b is not None:
            for cat, types in _POI_CATEGORY_TO_BUILDING_TYPES.items():
                if b.building_type in types:
                    poi_by_category[cat].append(pid)
                    break
        elif o is not None:
            for cat, types in _POI_CATEGORY_OUTDOOR_TYPES.items():
                if o.area_type in types:
                    poi_by_category[cat].append(pid)
                    break

    for attempt in range(5):
        home_pool = tuple(sorted(rng.sample(home_in, home_count)))
        work_pool = tuple(sorted(_sample_with_quotas(
            quotas.work, work_by_type, fallback_pool=work_in,
            target_count=work_count, rng=rng,
        )))
        poi_pool = tuple(sorted(_sample_with_quotas(
            quotas.poi, poi_by_category, fallback_pool=poi_in,
            target_count=poi_count, rng=rng,
        )))

        h, w, p = set(home_pool), set(work_pool), set(poi_pool)
        if not (h & w) and not (h & p) and not (w & p):
            return LocationPools(
                home_pool=home_pool,
                work_pool=work_pool,
                poi_pool=poi_pool,
                target_location=None,
            ).validate(atlas)

    raise LocationPoolError(
        f"failed to draw disjoint pools after 5 retries "
        f"(home/work/poi pool size {len(home_in)}/{len(work_in)}/{len(poi_in)})"
    )
