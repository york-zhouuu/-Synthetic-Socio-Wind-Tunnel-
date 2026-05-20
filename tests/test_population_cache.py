"""backlog 1.7 H (2026-05-20): population cache regression.

Verifies `cached_sample_population` skips the underlying compute when
keys match, recomputes when any key input changes, and falls back
gracefully on cache corruption / env disable.

Cache scope (narrow): only `sample_population` output. We do NOT cache
`build_location_pools` because it consumes the caller's rng and any
skip would break downstream scripted-plan determinism.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from unittest.mock import patch

import pytest

from synthetic_socio_wind_tunnel import LANE_COVE_PROFILE
from synthetic_socio_wind_tunnel.agent import build_location_pools
from synthetic_socio_wind_tunnel.cartography.lanecove import (
    create_atlas_from_osm,
)
from synthetic_socio_wind_tunnel.data_loader.population_cache import (
    cached_sample_population,
)


@pytest.fixture(scope="module")
def atlas():
    return create_atlas_from_osm()


@pytest.fixture
def tmp_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("POPULATION_CACHE_DIR", str(tmp_path / "popcache"))
    monkeypatch.delenv("POPULATION_CACHE_DISABLE", raising=False)
    return tmp_path / "popcache"


def _make_profile(size=30):
    return LANE_COVE_PROFILE.model_copy(update={"name": "t", "size": size})


def _make_pools(atlas, seed=42, n_agents=30):
    rng = random.Random(seed)
    return build_location_pools(
        atlas, home_count=max(40, n_agents // 2),
        n_agents=n_agents, rng=rng,
    )


# Scenario: first call computes + caches; second call returns equivalent result
def test_second_call_returns_cached_profiles(atlas, tmp_cache):
    profile = _make_profile(size=30)
    pools = _make_pools(atlas, seed=42, n_agents=30)
    profiles_1 = cached_sample_population(
        profile, seed=42, pools=pools, atlas=atlas, num_protagonists=3,
    )
    files = list(tmp_cache.glob("*.json"))
    assert len(files) == 1
    cached_payload = json.loads(files[0].read_text())
    assert cached_payload["schema_version"] == "1"
    assert cached_payload["key_inputs"]["seed"] == 42

    profiles_2 = cached_sample_population(
        profile, seed=42, pools=pools, atlas=atlas, num_protagonists=3,
    )
    assert len(profiles_2) == len(profiles_1)
    for p1, p2 in zip(profiles_1, profiles_2):
        assert p1.agent_id == p2.agent_id
        assert p1.age == p2.age
        assert p1.home_location == p2.home_location
        assert p1.work_mode == p2.work_mode


# Scenario: cache HIT really skips sample_population (not just returns equal data)
def test_cache_hit_skips_sample_population(atlas, tmp_cache):
    profile = _make_profile(size=30)
    pools = _make_pools(atlas, seed=42, n_agents=30)
    # prime
    cached_sample_population(profile, seed=42, pools=pools, atlas=atlas)
    # next call: blow up if sample_population is called
    with patch(
        "synthetic_socio_wind_tunnel.agent.population.sample_population",
        side_effect=AssertionError("should not be called on HIT"),
    ):
        profiles = cached_sample_population(
            profile, seed=42, pools=pools, atlas=atlas,
        )
    assert profiles  # cache served it without calling the underlying


# Scenario: changing seed invalidates cache
def test_different_seed_new_cache_entry(atlas, tmp_cache):
    profile = _make_profile(size=30)
    pools = _make_pools(atlas, seed=42, n_agents=30)
    cached_sample_population(profile, seed=42, pools=pools, atlas=atlas)
    cached_sample_population(profile, seed=43, pools=pools, atlas=atlas)
    assert len(list(tmp_cache.glob("*.json"))) == 2


# Scenario: changing pools (different n_agents → different pool tuples)
def test_different_pools_new_cache_entry(atlas, tmp_cache):
    profile_30 = _make_profile(size=30)
    profile_50 = _make_profile(size=50)
    pools_30 = _make_pools(atlas, seed=42, n_agents=30)
    pools_50 = _make_pools(atlas, seed=42, n_agents=50)
    cached_sample_population(profile_30, seed=42, pools=pools_30, atlas=atlas)
    cached_sample_population(profile_50, seed=42, pools=pools_50, atlas=atlas)
    assert len(list(tmp_cache.glob("*.json"))) == 2


# Scenario: env POPULATION_CACHE_DISABLE=1 bypasses cache
def test_disabled_cache_bypasses_read_and_write(atlas, tmp_path, monkeypatch):
    monkeypatch.setenv("POPULATION_CACHE_DIR", str(tmp_path / "popcache"))
    monkeypatch.setenv("POPULATION_CACHE_DISABLE", "1")
    profile = _make_profile(size=30)
    pools = _make_pools(atlas, seed=42, n_agents=30)
    cached_sample_population(profile, seed=42, pools=pools, atlas=atlas)
    assert not (tmp_path / "popcache").exists() or not list(
        (tmp_path / "popcache").glob("*.json"),
    )


# Scenario: malformed cache file → fall back to recompute, log warning
def test_malformed_cache_falls_back_to_compute(atlas, tmp_cache, caplog):
    import logging
    profile = _make_profile(size=30)
    pools = _make_pools(atlas, seed=42, n_agents=30)
    cached_sample_population(profile, seed=42, pools=pools, atlas=atlas)
    files = list(tmp_cache.glob("*.json"))
    files[0].write_text("garbage json {{{")
    with caplog.at_level(logging.WARNING):
        profiles = cached_sample_population(
            profile, seed=42, pools=pools, atlas=atlas,
        )
    assert profiles
    assert any("malformed cache" in r.message for r in caplog.records)


# Scenario: same profile (different .name) reuses cache (digest excludes name)
def test_profile_name_independence(atlas, tmp_cache):
    pools = _make_pools(atlas, seed=42, n_agents=30)
    profile_a = LANE_COVE_PROFILE.model_copy(update={"name": "alpha", "size": 30})
    profile_b = LANE_COVE_PROFILE.model_copy(update={"name": "beta", "size": 30})
    cached_sample_population(profile_a, seed=42, pools=pools, atlas=atlas)
    cached_sample_population(profile_b, seed=42, pools=pools, atlas=atlas)
    # only one cache entry — name doesn't affect digest
    assert len(list(tmp_cache.glob("*.json"))) == 1


# Real-artifact integration: caching SHALL NOT change the output
# vs uncached sample_population for the same inputs (determinism)
def test_cached_output_matches_uncached(atlas, tmp_cache, monkeypatch):
    from synthetic_socio_wind_tunnel.agent.population import sample_population
    profile = _make_profile(size=30)
    pools = _make_pools(atlas, seed=42, n_agents=30)
    # uncached (env disabled)
    monkeypatch.setenv("POPULATION_CACHE_DISABLE", "1")
    uncached = sample_population(profile, seed=42, pools=pools, atlas=atlas)
    # cached (env clean)
    monkeypatch.delenv("POPULATION_CACHE_DISABLE")
    cached_a = cached_sample_population(profile, seed=42, pools=pools, atlas=atlas)
    cached_b = cached_sample_population(profile, seed=42, pools=pools, atlas=atlas)
    # all three SHALL match on key fields
    for u, a, b in zip(uncached, cached_a, cached_b):
        assert u.agent_id == a.agent_id == b.agent_id
        assert u.age == a.age == b.age
        assert u.home_location == a.home_location == b.home_location
