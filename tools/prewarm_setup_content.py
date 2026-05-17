"""prewarm_setup_content — offline slow generation of per-seed setup cache.

Built to permanently solve the D2 attempt 3 catastrophe (2026-05-16) where
the publishable suite generated `[aitown] life_history: 0 events across
500 protag` because 4 worker × 500 concurrent LLM calls overwhelmed the
DeepSeek server.

By generating life_history + identity_text **offline** at low concurrency
(default 4) ahead of any publishable run, every subsequent suite call
becomes a cache HIT — zero LLM cost in setup phase, deterministic content,
no concurrent-burst pattern.

## Usage

    # Default: seeds 42-45 (β=4), concurrency 4, sonnet tier
    python tools/prewarm_setup_content.py

    # Explicit range
    python tools/prewarm_setup_content.py --seeds 42-45

    # CSV
    python tools/prewarm_setup_content.py --seeds 42,43,44

    # Force re-generate even if cache present
    python tools/prewarm_setup_content.py --seeds 42 --force

    # Lower concurrency (safer if rate-limit issues)
    python tools/prewarm_setup_content.py --concurrency 2

## Exit codes
- 0: all seeds completed (per-seed fallback warnings still exit 0)
- 1: at least one seed raised exception during generation
- 2: CLI / environment error (bad args, missing API key)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Auto-load <repo>/.env so DEEPSEEK_API_KEY(S) / GEMINI_API_KEY come from
# the canonical .env file without needing a shell export. Same convention
# as tools/run_variant_suite.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import load_dotenv as _load_dotenv  # noqa: E402
_load_dotenv()

logger = logging.getLogger("prewarm_setup_content")


def _parse_seed_range(value: str) -> list[int]:
    """Parse '42-56' (inclusive range) or '42,43,44' CSV into list of ints.

    Raises ValueError on malformed input.
    """
    value = (value or "").strip()
    if not value:
        raise ValueError("seeds value is empty")
    if "-" in value and "," not in value:
        a, _, b = value.partition("-")
        a_int, b_int = int(a), int(b)
        if a_int > b_int:
            raise ValueError(f"seed range start ({a_int}) > end ({b_int})")
        return list(range(a_int, b_int + 1))
    if "," in value:
        return [int(s.strip()) for s in value.split(",") if s.strip()]
    # Single seed
    return [int(value)]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prewarm_setup_content",
        description="Offline prewarm of per-seed setup cache (life_history + identity_text).",
    )
    p.add_argument(
        "--seeds", default="42-45",
        help="Seed range '42-45' (inclusive) or CSV '42,43,44'. Default: 42-45 "
             "(β=4 publishable; downgraded from β=30 → β=10 (2026-05-17) → "
             "β=4 (2026-05-18) per openspec/specs/experimental-design/spec.md)",
    )
    p.add_argument(
        "--concurrency", type=int, default=4,
        help="Max concurrent LLM calls (default 4 — keep low to avoid bursts)",
    )
    p.add_argument(
        "--batch-sleep", type=float, default=0.1,
        help="Sleep seconds between batches (default 0.1s)",
    )
    p.add_argument(
        "--tier", default="sonnet", choices=("sonnet", "haiku"),
        help="LLM tier for generation (default sonnet for quality)",
    )
    p.add_argument(
        "--provider", default="deepseek",
        choices=("deepseek", "anthropic", "gemini"),
        help="LLM provider (default deepseek)",
    )
    p.add_argument(
        "--n-records", type=int, default=20,
        help="life_history records per protagonist (default 20)",
    )
    p.add_argument(
        "--prompt-version", default="v2",
        help="life_history prompt template version (default v2)",
    )
    p.add_argument(
        "--n-agents", type=int, default=1000,
        help="Total agent count per seed (default 1000 — matches publishable)",
    )
    p.add_argument(
        "--num-protag", type=int, default=500,
        help="Protagonist count per seed (default 500)",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Re-generate even if cache file already exists",
    )
    p.add_argument(
        "--cache-dir", default=None,
        help="Override cache dir (default <repo>/data/setup_content_cache/)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print plan, do not call LLMs or write files",
    )
    p.add_argument(
        "--verbose", "-v", action="count", default=0,
        help="Increase verbosity",
    )
    return p


async def _prewarm_one_seed(
    *,
    seed: int,
    n_agents: int,
    num_protag: int,
    n_records: int,
    prompt_version: str,
    tier: str,
    provider: str,
    concurrency: int,
    batch_sleep: float,
    cache_dir: Path | None,
    force: bool,
    dry_run: bool,
) -> dict:
    """Run prewarm for one seed. Returns {'seed', 'cache_path',
    'n_protag', 'fallback_count', 'wall_seconds', 'skipped': bool}."""
    from synthetic_socio_wind_tunnel.agent import build_location_pools
    from synthetic_socio_wind_tunnel.agent.population import (
        LANE_COVE_PROFILE,
        sample_population,
    )
    from synthetic_socio_wind_tunnel.cartography.lanecove import (
        create_atlas_from_osm,
    )
    from synthetic_socio_wind_tunnel.data_loader import (
        generate_identity_text_for_protagonists,
        generate_life_history_for_protagonists,
        is_cache_complete,
        load_archetypes,
        load_setup_cache,
        save_setup_cache,
    )
    from synthetic_socio_wind_tunnel.data_loader.setup_cache import (
        SimulationContentCache,
    )

    t0 = time.time()

    # Check skip path
    existing = load_setup_cache(seed, cache_dir=cache_dir)
    if existing is not None and not force:
        # Need profile list to check completeness — build a fake one
        # with just agent_ids to avoid running full sample_population
        logger.info("[seed=%d] cache exists at expected path", seed)
        if existing.life_history and existing.identity_text:
            logger.info(
                "[seed=%d] SKIPPED — cache already has %d life_history + %d "
                "identity_text entries (use --force to regenerate)",
                seed, len(existing.life_history), len(existing.identity_text),
            )
            return {
                "seed": seed, "cache_path": None,
                "n_protag": len(existing.life_history),
                "fallback_count": len(existing.failed_protag),
                "wall_seconds": time.time() - t0,
                "skipped": True,
            }

    # Build profiles
    import random
    rng = random.Random(seed)
    atlas = create_atlas_from_osm()
    pools = build_location_pools(
        atlas, home_count=max(40, n_agents // 2),
        n_agents=n_agents, rng=rng,
    )
    profile_template = LANE_COVE_PROFILE.model_copy(update={
        "name": "prewarm",
        "size": n_agents,
    })
    profiles = sample_population(
        profile_template,
        seed=seed,
        pools=pools,
        atlas=atlas,
        num_protagonists=num_protag,
    )

    n_protag_actual = sum(1 for p in profiles if p.is_protagonist)
    logger.info(
        "[seed=%d] sampled %d agents (%d protag)",
        seed, len(profiles), n_protag_actual,
    )

    if dry_run:
        logger.info(
            "[seed=%d] DRY-RUN — would generate %d life_history + %d "
            "identity_text via %s tier",
            seed, n_protag_actual, n_protag_actual, tier,
        )
        return {
            "seed": seed, "cache_path": None,
            "n_protag": n_protag_actual,
            "fallback_count": 0,
            "wall_seconds": time.time() - t0,
            "skipped": False,
        }

    # Build LLM client
    from tools.tier_llm_factory import build_tier_clients
    tier_clients = build_tier_clients(provider=provider)
    llm_client = (
        tier_clients.get(tier)
        or tier_clients.get("haiku")
        or next(iter(tier_clients.values()))
    )

    # Inject the chosen tier's model into generate_*_for_one via `model=...`
    archs = load_archetypes()

    # Step 1: life_history (concurrency-controlled via batch_size)
    logger.info(
        "[seed=%d] starting life_history generation "
        "(batch_size=%d, n_records=%d, prompt=%s)",
        seed, concurrency, n_records, prompt_version,
    )
    life_history, life_failed = await generate_life_history_for_protagonists(
        profiles,
        llm_client=llm_client,
        archetypes=archs,
        n_records_per_protag=n_records,
        batch_size=concurrency,
        prompt_version=prompt_version,
        max_retries=2,
        fallback_to_template=True,
    )
    logger.info(
        "[seed=%d] life_history done — %d/%d ok, %d fell back to template",
        seed, n_protag_actual - len(life_failed),
        n_protag_actual, len(life_failed),
    )

    # Optional sleep between phases
    if batch_sleep > 0:
        await asyncio.sleep(batch_sleep)

    # Step 2: identity_text
    logger.info(
        "[seed=%d] starting identity_text generation (batch_size=%d)",
        seed, concurrency,
    )
    identity_text, identity_failed = await generate_identity_text_for_protagonists(
        profiles,
        llm_client=llm_client,
        archetypes=archs,
        life_history_by_agent=life_history,
        batch_size=concurrency,
        prompt_version="v1",
        max_retries=2,
    )
    logger.info(
        "[seed=%d] identity_text done — %d/%d ok, %d fell back to template",
        seed, n_protag_actual - len(identity_failed),
        n_protag_actual, len(identity_failed),
    )

    # Serialize life_history records → dict for cache storage
    life_history_json = {
        aid: [
            {
                "record_id": r.record_id,
                "agent_id": r.agent_id,
                "title": r.title,
                "content": r.content,
                "years_ago": r.years_ago,
                "location_hint": r.location_hint,
                "importance": r.importance,
                "tags": list(r.tags),
            }
            for r in recs
        ]
        for aid, recs in life_history.items()
    }

    # Union of failed protag (any failure in either phase)
    failed_union = sorted(set(life_failed) | set(identity_failed))

    cache = SimulationContentCache(
        seed=seed,
        generated_at=datetime.now(UTC).replace(tzinfo=None),
        generator={
            "tier": tier,
            "provider": provider,
            "n_records_per_protag": n_records,
            "prompt_version": prompt_version,
            "concurrency": concurrency,
            "n_agents": n_agents,
            "num_protag": num_protag,
        },
        life_history=life_history_json,
        identity_text=identity_text,
        failed_protag=failed_union,
    )

    cache_path = save_setup_cache(seed, cache, cache_dir=cache_dir)
    wall = time.time() - t0

    # Verify completeness post-write
    reloaded = load_setup_cache(seed, cache_dir=cache_dir)
    complete = (
        reloaded is not None
        and is_cache_complete(reloaded, profiles)
    )
    if not complete:
        logger.warning(
            "[seed=%d] cache written but is_cache_complete=False — "
            "verify profiles match between prewarm and run",
            seed,
        )

    fallback_pct = (
        100.0 * len(failed_union) / max(1, n_protag_actual)
    )
    log_fn = logger.warning if fallback_pct > 5.0 else logger.info
    log_fn(
        "[seed=%d] WROTE %s in %.1fs — %d/%d fallback (%.1f%%)",
        seed, cache_path, wall,
        len(failed_union), n_protag_actual, fallback_pct,
    )

    return {
        "seed": seed,
        "cache_path": str(cache_path),
        "n_protag": n_protag_actual,
        "fallback_count": len(failed_union),
        "wall_seconds": wall,
        "skipped": False,
    }


async def _prewarm_all(args: argparse.Namespace, seeds: list[int]) -> int:
    """Sequentially prewarm each seed. Returns exit code."""
    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    overall_t0 = time.time()
    results = []
    any_error = False

    for seed in seeds:
        try:
            result = await _prewarm_one_seed(
                seed=seed,
                n_agents=args.n_agents,
                num_protag=args.num_protag,
                n_records=args.n_records,
                prompt_version=args.prompt_version,
                tier=args.tier,
                provider=args.provider,
                concurrency=args.concurrency,
                batch_sleep=args.batch_sleep,
                cache_dir=cache_dir,
                force=args.force,
                dry_run=args.dry_run,
            )
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[seed=%d] FAILED with exception: %r", seed, exc)
            any_error = True
            results.append({
                "seed": seed, "error": repr(exc), "skipped": False,
            })

    elapsed = time.time() - overall_t0
    n_skipped = sum(1 for r in results if r.get("skipped"))
    n_written = sum(1 for r in results if r.get("cache_path"))
    n_fallback = sum(r.get("fallback_count", 0) for r in results)

    logger.info(
        "=== prewarm done in %.1fs — %d/%d seeds (%d skipped, %d wrote, "
        "%d total fallbacks) ===",
        elapsed, len(seeds), len(seeds), n_skipped, n_written, n_fallback,
    )

    return 1 if any_error else 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Logging
    level = logging.WARNING - (10 * args.verbose)
    if level < logging.DEBUG:
        level = logging.DEBUG
    logging.basicConfig(
        level=max(level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        seeds = _parse_seed_range(args.seeds)
    except ValueError as exc:
        print(f"error: invalid --seeds: {exc}", file=sys.stderr)
        return 2

    # Provider key check
    if not args.dry_run:
        if args.provider == "deepseek" and not (
            os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEYS")
        ):
            print(
                "error: --provider deepseek but no DEEPSEEK_API_KEY(S) in env",
                file=sys.stderr,
            )
            return 2
        if args.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
            print("error: --provider anthropic but no ANTHROPIC_API_KEY in env",
                  file=sys.stderr)
            return 2
        if args.provider == "gemini" and not os.environ.get("GEMINI_API_KEY"):
            print("error: --provider gemini but no GEMINI_API_KEY in env",
                  file=sys.stderr)
            return 2

    logger.info(
        "prewarm: seeds=%s concurrency=%d tier=%s provider=%s n_records=%d "
        "prompt=%s n_agents=%d num_protag=%d force=%s dry_run=%s",
        seeds, args.concurrency, args.tier, args.provider, args.n_records,
        args.prompt_version, args.n_agents, args.num_protag, args.force,
        args.dry_run,
    )

    return asyncio.run(_prewarm_all(args, seeds))


if __name__ == "__main__":
    sys.exit(main())
