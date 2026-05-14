"""A2 / realism-household-coupling: HouseholdRegistry + clustering tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def sampled_population():
    from synthetic_socio_wind_tunnel.agent import (
        HouseholdRegistry,
        sample_population,
        LANE_COVE_PROFILE,
    )
    profile = LANE_COVE_PROFILE.model_copy(update={"name": "test", "size": 200})
    agents = sample_population(profile, seed=42, generate_identity=False)
    return agents, HouseholdRegistry.from_profiles(agents)


class TestHouseholdIdAssigned:

    def test_every_agent_has_non_empty_household_id(self, sampled_population):
        agents, _ = sampled_population
        for a in agents:
            assert a.household_id, f"{a.agent_id} has empty household_id"

    def test_household_role_in_4_values(self, sampled_population):
        agents, _ = sampled_population
        valid = {"parent", "child", "partner", "lone"}
        for a in agents:
            assert a.household_role in valid

    def test_distinct_household_count_in_reasonable_range(self, sampled_population):
        agents, reg = sampled_population
        # 200 agents with mixed family_composition → ~70-150 households
        assert 50 <= reg.household_count() <= 180


class TestSharedHomeLocation:

    def test_same_household_share_home_location(self, sampled_population):
        agents, reg = sampled_population
        from collections import defaultdict
        homes_by_hh: dict[str, set[str]] = defaultdict(set)
        for a in agents:
            homes_by_hh[a.household_id].add(a.home_location)
        for hh, homes in homes_by_hh.items():
            assert len(homes) == 1, \
                f"household {hh} has multiple home_locations: {homes}"


class TestRegistryAPI:

    def test_members_of_returns_all(self, sampled_population):
        agents, reg = sampled_population
        for hh_id in {a.household_id for a in agents}:
            members = reg.members_of(hh_id)
            assert all(p.household_id == hh_id for p in members)

    def test_household_of_lookup(self, sampled_population):
        agents, reg = sampled_population
        for a in agents:
            assert reg.household_of(a.agent_id) == a.household_id

    def test_siblings_excludes_self(self, sampled_population):
        agents, reg = sampled_population
        for a in agents[:20]:
            sibs = reg.siblings_of(a.agent_id)
            assert all(p.agent_id != a.agent_id for p in sibs)

    def test_home_location_for_returns_shared(self, sampled_population):
        agents, reg = sampled_population
        for a in agents[:20]:
            home = reg.home_location_for(a.household_id)
            assert home == a.home_location
