"""Per-seed cache for sample_population output.

backlog 1.7 H (2026-05-20): `sample_population` is a deterministic
function of (seed, profile, pools, atlas, num_protagonists, identity
flags) — same inputs always produce the same output. For 1000 agents
it takes ~10-20s of CPU per spawn. Across a 14-day publishable run
with 4 workers and a couple restarts that adds up to several minutes
of wall time.

Why NOT cache `build_location_pools` too: that function consumes the
caller's `rng: random.Random` to advance its state. Downstream code
(`build_scripted_plan`, fallback `home_loc` selection) depends on
that post-build rng state. If we skipped the build_location_pools call
on cache HIT, the rng would not advance and the resulting agent
scripted plans would diverge from the uncached path — silently
breaking determinism across spawns.

`sample_population` is safer to cache because it creates its OWN
`random.Random(seed)` internally and doesn't touch the caller's rng.

Public API:
- `cached_sample_population(profile, seed, pools, atlas, ...)` — cache
  wrapper with the same signature as `sample_population` modulo the
  `llm_client` arg (skipped under `protag_llm_variation=False`, which
  is the publishable setup-content-cache path).

Env:
- `POPULATION_CACHE_DISABLE=1` — bypass cache entirely
- `POPULATION_CACHE_DIR` — override default `data/population_cache/v1/`
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.location_pools import LocationPools
    from synthetic_socio_wind_tunnel.agent.population import (
        AgentProfile, PopulationProfile,
    )
    from synthetic_socio_wind_tunnel.atlas import Atlas

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "1"


def _cache_dir() -> Path:
    override = os.environ.get("POPULATION_CACHE_DIR")
    if override:
        return Path(override)
    return Path("data/population_cache/v1")


def _disabled() -> bool:
    return os.environ.get("POPULATION_CACHE_DISABLE", "0") == "1"


def _profile_digest(profile: "PopulationProfile") -> str:
    raw = profile.model_dump_json(exclude={"name"})
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _pools_digest(pools: "LocationPools") -> str:
    """Hash the 3 pool tuples in their actual (order-significant) form.
    `sample_population` uses `rng.choice(pools.home_pool)` so iteration
    order changes output."""
    raw = json.dumps({
        "home": list(pools.home_pool),
        "work": list(pools.work_pool),
        "poi": list(pools.poi_pool),
    }, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _key(
    *, seed: int, num_protagonists: int, atlas_region_id: str,
    profile_digest: str, pools_digest: str,
    generate_identity: bool, protag_llm_variation: bool,
) -> tuple[str, dict]:
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "seed": int(seed),
        "num_protagonists": int(num_protagonists),
        "atlas_region_id": str(atlas_region_id),
        "profile_digest": str(profile_digest),
        "pools_digest": str(pools_digest),
        "generate_identity": bool(generate_identity),
        "protag_llm_variation": bool(protag_llm_variation),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return digest, payload


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, default=str)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent),
        prefix=".swt-popcache-", suffix=".json.tmp", delete=False,
    ) as tf:
        tf.write(body)
        tf.flush()
        try:
            os.fsync(tf.fileno())
        except OSError:
            pass
        tmp_name = tf.name
    os.rename(tmp_name, path)


def _serialize_profiles(profiles: list["AgentProfile"]) -> list[dict]:
    return [p.model_dump(mode="json") for p in profiles]


def _deserialize_profiles(raw: list[dict]) -> list["AgentProfile"]:
    from synthetic_socio_wind_tunnel.agent.population import AgentProfile
    return [AgentProfile.model_validate(d) for d in raw]


def cached_sample_population(
    profile: "PopulationProfile",
    *,
    seed: int,
    pools: "LocationPools",
    atlas: "Atlas",
    num_protagonists: int = 0,
    generate_identity: bool = False,
    protag_llm_variation: bool = True,
) -> list["AgentProfile"]:
    """Drop-in replacement for `sample_population(..., llm_client=None)`
    that caches output by content-hashed inputs.

    Cache is bypassed (always recompute) when env
    `POPULATION_CACHE_DISABLE=1`. Cache read failures fall back to
    recomputing; cache write failures log a warning but don't crash.
    """
    from synthetic_socio_wind_tunnel.agent.population import sample_population

    region_id = getattr(getattr(atlas, "region", None), "id", "<unknown>")
    digest, key_inputs = _key(
        seed=seed, num_protagonists=num_protagonists,
        atlas_region_id=region_id,
        profile_digest=_profile_digest(profile),
        pools_digest=_pools_digest(pools),
        generate_identity=generate_identity,
        protag_llm_variation=protag_llm_variation,
    )
    cache_path = _cache_dir() / f"{digest}.json"

    if not _disabled() and cache_path.exists():
        try:
            with cache_path.open(encoding="utf-8") as fh:
                cached = json.load(fh)
            if (
                cached.get("schema_version") == _SCHEMA_VERSION
                and cached.get("key_inputs") == key_inputs
            ):
                profiles = _deserialize_profiles(cached["profiles"])
                logger.info(
                    "[population_cache] HIT seed=%d profile.size=%d "
                    "key=%s (skipped sample_population)",
                    seed, profile.size, digest,
                )
                return profiles
            logger.warning(
                "[population_cache] key_inputs mismatch in %s; recomputing",
                cache_path,
            )
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning(
                "[population_cache] malformed cache at %s (%s); recomputing",
                cache_path, exc,
            )

    logger.info(
        "[population_cache] MISS seed=%d profile.size=%d "
        "(computing sample_population)",
        seed, profile.size,
    )
    profiles = sample_population(
        profile, seed=seed, pools=pools, atlas=atlas,
        num_protagonists=num_protagonists,
        generate_identity=generate_identity,
        llm_client=None,
        protag_llm_variation=protag_llm_variation,
    )

    if not _disabled():
        try:
            payload = {
                "schema_version": _SCHEMA_VERSION,
                "key_inputs": key_inputs,
                "profiles": _serialize_profiles(profiles),
            }
            _atomic_write_json(cache_path, payload)
        except OSError as exc:
            logger.warning(
                "[population_cache] write failed for %s (%s) — "
                "this spawn was uncached; future spawns will retry",
                cache_path, exc,
            )

    return profiles


__all__ = ["cached_sample_population"]
