#!/usr/bin/env python3
"""
run_variant_suite — 跨 variant × 跨 seed 的 Rival Hypothesis Contest CLI

职责：
- 对每 variant 跑 N seed × N day（复用 policy-hack + multi-day-run）
- 每 run 挂 TickMetricsRecorder 采集数据
- Per-variant 聚合（SuiteAggregate）
- Cross-variant contest（ContestReport）
- 产出五幕 Markdown 报告（report.md）

Usage:
    python3 tools/run_variant_suite.py \\
        --variants baseline,hyperlocal_push,global_distraction,phone_friction,
                   shared_anchor,catalyst_seeding \\
        --seeds 30 --num-days 14 --agents 100 \\
        --mode publishable --phase-days 4,6,4 \\
        --suite-name thesis_v1

Output:
    data/experiments/<timestamp>_<suite_name>/
    ├── variant_<name>/
    │   ├── seed_<N>.json            (MultiDayResult + RunMetrics)
    │   └── aggregate.json           (SuiteAggregate)
    ├── contest.json
    └── report.md
"""

from __future__ import annotations

import argparse
import faulthandler
import json
import os
import random
import signal
import sys
import time
from pathlib import Path
from typing import Any

# Auto-load <repo>/.env so --use-real-llm picks up GEMINI_API_KEY without
# requiring shell export. Path-jiggling so the import works regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import load_dotenv as _load_dotenv  # noqa: E402
_load_dotenv()

# 2026-05-20 root cause diagnosis (D4 path):
# Install faulthandler so when a worker hangs, we can SIGUSR2 it to dump
# full Python stacks (all threads) to stderr without needing sudo / py-spy.
# This is the same mechanism Python uses for `--enable-fault-handler`.
# Crucially, faulthandler uses a dedicated background thread that's
# unaffected by the GIL or asyncio loop being blocked — so we get the
# real Python frame even when SIGUSR1 (asyncio signal handler) doesn't
# respond.
#
# Env-controlled to keep CI clean:
#   FAULTHANDLER_SIGUSR2=1    register USR2 handler (default ON for workers)
#   FAULTHANDLER_AUTO_DUMP=300  auto-dump every N seconds (off if unset)
if os.environ.get("FAULTHANDLER_SIGUSR2", "1") == "1":
    faulthandler.register(signal.SIGUSR2, all_threads=True, chain=False)
_auto_dump_sec = os.environ.get("FAULTHANDLER_AUTO_DUMP")
if _auto_dump_sec:
    try:
        faulthandler.dump_traceback_later(
            int(_auto_dump_sec), repeat=True, exit=False,
        )
    except (ValueError, RuntimeError):
        pass
from datetime import date, datetime
from pathlib import Path

# Reuse smoke_experiment_demo helpers (atlas / destination picker only;
# build_scripted_plan migrated to synthetic_socio_wind_tunnel.agent).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_experiment_demo import _pick_connected_destinations  # type: ignore

from synthetic_socio_wind_tunnel.agent import build_scripted_plan

from suite_stub_llm import (  # type: ignore
    _pick_community_location,
    make_llm_client,
)

from synthetic_socio_wind_tunnel.agent import (
    AgentRuntime,
    LANE_COVE_PROFILE,
    Planner,
    sample_population,
)
from synthetic_socio_wind_tunnel.memory import MemoryService
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention import AttentionService
from synthetic_socio_wind_tunnel.cartography.lanecove import create_atlas_from_osm
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.metrics import (
    RunMetrics,
    SuiteAggregate,
    TickMetricsRecorder,
    build_contest_report,
    build_run_metrics,
    build_suite_aggregate,
    write_markdown,
)
from synthetic_socio_wind_tunnel.orchestrator import (
    MultiDayResult,
    MultiDayRunner,
    Orchestrator,
)
from synthetic_socio_wind_tunnel.policy_hack import (
    VARIANTS,
    PhaseController,
    Variant,
    VariantRunnerAdapter,
)


_KNOWN_VARIANTS = ["baseline"] + sorted(VARIANTS.keys())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--variants", type=str,
                   default=",".join(_KNOWN_VARIANTS),
                   help=f"comma-separated; choices: {','.join(_KNOWN_VARIANTS)}")
    p.add_argument("--seeds", type=int, default=30)
    p.add_argument("--seed-start", type=int, default=42,
                   help="Base seed value. Suite uses range(seed_start, "
                        "seed_start + seeds). Default 42 preserves the "
                        "historical 42..N convention. Use a different base "
                        "to run parallel sub-suites that don't collide on "
                        "the same seed_N.json files.")
    p.add_argument("--num-days", type=int, default=14)
    p.add_argument("--agents", type=int, default=100)
    p.add_argument("--num-protagonists", type=int, default=None,
                   help="LLM-driven protagonist count (Sonnet tier). Default "
                        "is 10%% of --agents. Set higher (e.g. 50%%) for "
                        "publishable runs so variant push effects aren't "
                        "diluted by 90%% scripted-only agents (A2 disclosure).")
    p.add_argument("--mode", choices=["dev", "publishable"], default="publishable")
    p.add_argument("--phase-days", type=str, default="4,6,4")
    p.add_argument("--start-date", type=str, default="2026-04-22")
    p.add_argument("--output-dir", type=Path, default=Path("data/experiments"))
    p.add_argument("--suite-name", type=str, default="rival_hypothesis_suite")
    p.add_argument("--use-real-llm", action="store_true",
                   help="Use anthropic Haiku for planner.replan "
                        "(default: zero-cost StubReplanLLM)")
    p.add_argument("--use-aitown", action="store_true",
                   help="Wire ai-town port: protag get full LLM dialogue + "
                        "do_something + reflection; lane cove data injected "
                        "(archetypes/shared_memories/life_history/social_priors). "
                        "Implies generate_identity=True at sample time.")
    p.add_argument("--aitown-provider",
                   choices=["gemini", "anthropic", "deepseek", "stub"],
                   default="gemini",
                   help="LLM provider for ai-town ops. gemini=GEMINI_API_KEY env "
                        "(default), anthropic=ANTHROPIC_API_KEY env, "
                        "deepseek=DEEPSEEK_API_KEY env (v4-pro for sonnet tier, "
                        "v4-flash for haiku/nano), stub=zero-cost deterministic.")
    p.add_argument("--suite-dir", type=Path, default=None,
                   help="Use this exact suite directory (skip the auto "
                        "timestamp-prefixed subdir). Required for --resume.")
    p.add_argument("--resume", action="store_true",
                   help="Skip seeds whose seed_<N>.json already exists in the "
                        "target variant_<X>/ subdir (load run_metrics from "
                        "disk instead). Skip whole variant if aggregate.json "
                        "exists. Use with --suite-dir.")
    p.add_argument("--resume-from-day", type=int, default=None,
                   help="run-resilience: force MultiDayRunner to start from "
                        "this day_index, overriding partial-file auto-detect. "
                        "Use 0 to force a fresh start.")
    p.add_argument("--resume-strategy",
                   choices=["auto", "snapshot-only", "partial-only", "none"],
                   default="auto",
                   help="tick-level-resume: how to pick up after a crash. "
                        "auto=snapshot priority, partial fallback (recommended); "
                        "snapshot-only=fail if no snapshot; "
                        "partial-only=skip snapshots, run-resilience behavior; "
                        "none=fresh start (overrides --resume).")
    p.add_argument("--skip-preflight", action="store_true",
                   help="Skip the 1000-agent × 1-day preflight smoke gate. "
                        "Publishable mode (--agents 1000 --num-days 14) "
                        "IGNORES this flag and always runs preflight (the "
                        "D1' scale-only-bug lesson).")
    p.add_argument("--workers", type=int, default=1,
                   help="Process-level parallelism: split variants across N "
                        "worker subprocesses, each running ALL seeds for one "
                        "variant against a shared --suite-dir. Coordinator "
                        "process aggregates at the end. Default 1 (serial). "
                        "Pick min(workers, len(variants)).")
    return p.parse_args()


_LIFE_HISTORY_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "life_history_cache"


async def _load_or_generate_life_history(
    *,
    seed: int,
    profiles,
    llm_client,
    archetypes,
    n_records_per_protag: int = 10,
    batch_size: int = 5,
):
    """LLM cost-saver: per-seed life_history cache keyed by agent_id.

    First time seed N is sampled, generates 500 protag life_histories via LLM
    and dumps to `data/life_history_cache/seed_<N>.json`. Subsequent calls for
    the same seed load from disk — zero LLM cost.

    Cache contract:
    - Key: agent_id (e.g. "a_42_0042")
    - Value: list[LifeHistoryRecord-as-dict]
    - Invalidation: only by deleting the cache file (deterministic + idempotent)

    If cache exists but partial coverage (some protag missing), only the
    missing ones are LLM-generated and merged into cache.
    """
    from synthetic_socio_wind_tunnel.data_loader.lanecove import (
        LifeHistoryRecord,
        generate_life_history_for_protagonists,
    )

    cache_file = _LIFE_HISTORY_CACHE_DIR / f"seed_{seed}.json"
    _LIFE_HISTORY_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing cache
    cached: dict[str, list[LifeHistoryRecord]] = {}
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for aid, recs in raw.items():
                cached[aid] = [
                    LifeHistoryRecord(
                        record_id=r["record_id"],
                        agent_id=r["agent_id"],
                        title=r["title"],
                        content=r["content"],
                        years_ago=float(r["years_ago"]),
                        location_hint=r.get("location_hint"),
                        importance=float(r["importance"]),
                        tags=tuple(r.get("tags", ())),
                    )
                    for r in recs
                ]
            print(
                f"[life_history_cache] loaded {len(cached)} protag from {cache_file.name}",
                file=sys.stderr,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"[life_history_cache] failed to load {cache_file.name}: {exc!r} "
                f"— regenerating from scratch",
                file=sys.stderr,
            )
            cached = {}

    # Figure out which protag we still need
    protag_ids = {p.agent_id for p in profiles if p.is_protagonist}
    missing_ids = protag_ids - set(cached.keys())

    if not missing_ids:
        print(
            f"[life_history_cache] HIT — all {len(protag_ids)} protag served from cache, "
            f"skipping LLM generation",
            file=sys.stderr,
        )
        # Filter to only protag that exist in this profile set (in case cache
        # has stale extras)
        return {aid: cached[aid] for aid in protag_ids}

    # Generate the missing ones
    missing_profiles = [p for p in profiles if p.agent_id in missing_ids]
    print(
        f"[life_history_cache] MISS — {len(missing_ids)}/{len(protag_ids)} protag "
        f"need LLM generation",
        file=sys.stderr,
    )
    newly_generated, failed_protag = await generate_life_history_for_protagonists(
        missing_profiles, llm_client=llm_client, archetypes=archetypes,
        n_records_per_protag=n_records_per_protag, batch_size=batch_size,
    )
    if failed_protag:
        print(
            f"[life_history_cache] WARN — {len(failed_protag)} protag fell back "
            f"to template (LLM exhausted retries): {failed_protag[:5]}"
            f"{'...' if len(failed_protag) > 5 else ''}",
            file=sys.stderr,
        )

    # Merge + persist atomically
    merged = {**cached, **newly_generated}
    tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {
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
                    for aid, recs in merged.items()
                },
                f, ensure_ascii=False, indent=2,
            )
            f.flush()
        import os as _os
        _os.replace(tmp, cache_file)
        print(
            f"[life_history_cache] persisted {len(merged)} protag → {cache_file.name}",
            file=sys.stderr,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"[life_history_cache] WARN — failed to persist cache: {exc!r} "
            f"(LLM result still used for current run)",
            file=sys.stderr,
        )
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    # Return only the requested protag (filter out any historical extras)
    return {aid: merged[aid] for aid in protag_ids if aid in merged}


async def _load_or_generate_setup_content(
    *,
    seed: int,
    profiles,
    llm_client,
    archetypes,
    n_records_per_protag: int = 20,
    batch_size: int = 4,
    tier: str = "sonnet",
    prompt_version: str = "v2",
):
    """setup-content-cache 2026-05-16: per-seed combined life_history +
    identity_text cache.

    Cache HIT (both present and complete for the given protag set):
      → returns `(life_history_records, identity_text)` with **zero LLM calls**

    Cache MISS / partial / schema invalidated:
      → falls back to in-suite generation, writes the new cache

    Returns:
      `(life_history: dict[agent_id → list[LifeHistoryRecord]],
        identity_text: dict[agent_id → str],
        cache_hit: bool)`
    """
    from datetime import UTC, datetime as _dt
    from synthetic_socio_wind_tunnel.data_loader import (
        generate_identity_text_for_protagonists,
        generate_life_history_for_protagonists,
        is_cache_complete,
        load_setup_cache,
        save_setup_cache,
    )
    from synthetic_socio_wind_tunnel.data_loader.lanecove import (
        LifeHistoryRecord,
    )
    from synthetic_socio_wind_tunnel.data_loader.setup_cache import (
        SimulationContentCache,
    )

    cache = load_setup_cache(seed)
    if cache is not None and is_cache_complete(cache, profiles):
        # HIT — reconstruct LifeHistoryRecord objects from raw dicts
        history_records: dict[str, list[LifeHistoryRecord]] = {}
        for aid, recs in cache.life_history.items():
            history_records[aid] = [
                LifeHistoryRecord(
                    record_id=r["record_id"],
                    agent_id=r["agent_id"],
                    title=r["title"],
                    content=r["content"],
                    years_ago=float(r["years_ago"]),
                    location_hint=r.get("location_hint"),
                    importance=float(r["importance"]),
                    tags=tuple(r.get("tags", ())),
                )
                for r in recs
            ]
        identity_text = dict(cache.identity_text)
        # Filter to current protag set
        protag_ids = {p.agent_id for p in profiles if p.is_protagonist}
        history_records = {
            aid: recs for aid, recs in history_records.items()
            if aid in protag_ids
        }
        identity_text = {
            aid: txt for aid, txt in identity_text.items()
            if aid in protag_ids
        }
        print(
            f"[setup_cache] HIT for seed={seed} — {len(history_records)} "
            f"life_history + {len(identity_text)} identity_text "
            f"(zero LLM)",
            file=sys.stderr,
        )
        return history_records, identity_text, True

    # MISS — generate online, write cache
    print(
        f"[setup_cache] MISS for seed={seed} — generating "
        f"(this should not happen in publishable; run prewarm first)",
        file=sys.stderr,
    )

    history_records, life_failed = await generate_life_history_for_protagonists(
        profiles,
        llm_client=llm_client,
        archetypes=archetypes,
        n_records_per_protag=n_records_per_protag,
        batch_size=batch_size,
        prompt_version=prompt_version,
        max_retries=2,
        fallback_to_template=True,
    )
    identity_text, identity_failed = await generate_identity_text_for_protagonists(
        profiles,
        llm_client=llm_client,
        archetypes=archetypes,
        life_history_by_agent=history_records,
        batch_size=batch_size,
        prompt_version="v1",
        max_retries=2,
    )
    failed_union = sorted(set(life_failed) | set(identity_failed))

    # Persist
    try:
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
            for aid, recs in history_records.items()
        }
        new_cache = SimulationContentCache(
            seed=seed,
            generated_at=_dt.now(UTC).replace(tzinfo=None),
            generator={
                "tier": tier,
                "n_records_per_protag": n_records_per_protag,
                "prompt_version": prompt_version,
                "concurrency": batch_size,
                "via": "run_variant_suite_fallback",
            },
            life_history=life_history_json,
            identity_text=identity_text,
            failed_protag=failed_union,
        )
        save_setup_cache(seed, new_cache)
        print(
            f"[setup_cache] wrote seed={seed} after MISS "
            f"({len(failed_union)} fallback)",
            file=sys.stderr,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"[setup_cache] WARN — failed to persist after MISS: {exc!r} "
            f"(content still used for this run)",
            file=sys.stderr,
        )

    return history_records, identity_text, False


def _staggered_submit(pool, fn, items, *, spacing_secs: float):
    """Submit `items` to `pool` with `spacing_secs` between submissions.

    Returns a list of futures in input order. `spacing_secs <= 0` submits
    all items back-to-back (no sleep). Single-item lists never sleep.

    Why: stagger-worker-spawn (2026-05-19). D2 attempt 6's 4-worker
    self-DDoS was caused by `pool.map(fn, variants)` submitting all 4
    futures within ~2 seconds, leading to 2000+ concurrent LLM HTTP
    posts to DeepSeek and server-side TCP drop. Spreading submissions
    by 5 min (default via `RESILIENCE_MIN_SPAWN_SPACING_SECS`) caps
    peak concurrency at single-worker level (~500 in-flight).
    """
    futures = []
    items_list = list(items)
    for i, item in enumerate(items_list):
        if i > 0 and spacing_secs > 0:
            time.sleep(spacing_secs)
        futures.append(pool.submit(fn, item))
    return futures


def _update_pids_json(suite_dir: Path, variant: str, pid: int) -> None:
    """Append `pid` for `variant` into `<suite_dir>/pids.json`.

    Schema: `{"workers": [<pid>, ...], "by_variant": {"<name>": <pid>}}`.
    Consumed by `tools/audit_run_health.py` to discover in-progress
    workers without needing pid headers in each worker_*.log.

    Idempotent on re-runs of the same variant (last write wins).
    """
    path = suite_dir / "pids.json"
    data: dict = {"workers": [], "by_variant": {}}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            data = {"workers": [], "by_variant": {}}
    by_var = data.setdefault("by_variant", {})
    by_var[variant] = pid
    data["workers"] = sorted(set(by_var.values()))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _parse_phase_days_to_dict(phase_days: str) -> dict[str, int]:
    """Split "4,6,4" → {"baseline_days":4,"intervention_days":6,"post_days":4}.

    Raises ValueError if not exactly 3 comma-separated ints.
    """
    parts = [int(x.strip()) for x in phase_days.split(",")]
    if len(parts) != 3:
        raise ValueError(f"--phase-days expects '4,6,4'; got {phase_days!r}")
    return {
        "baseline_days": parts[0],
        "intervention_days": parts[1],
        "post_days": parts[2],
    }


def _build_variant(
    variant_name: str,
    phase_days: str,
    *,
    target_location: str | None,
) -> tuple[Variant | None, PhaseController]:
    """解析 phase + 可选 variant 实例化。baseline 返 (None, controller)。"""
    pc = _parse_phase_days_to_dict(phase_days)
    controller = PhaseController(
        baseline_days=pc["baseline_days"],
        intervention_days=pc["intervention_days"],
        post_days=pc["post_days"],
    )
    if variant_name == "baseline":
        return None, controller
    cls = VARIANTS[variant_name]
    kwargs: dict = {}
    if variant_name == "hyperlocal_push" and target_location is not None:
        kwargs["target_location"] = target_location
    variant = cls(**kwargs) if kwargs else cls()
    return variant, controller


def _setup_aitown_stack(
    *,
    orchestrator,
    runtimes,
    memory_service,
    social_graph,
    tier_clients: dict,
    seed: int,
    sim_start_time,
    pools=None,
) -> dict:
    """Stage 4 — wire ai-town port to multi-day runner.

    Steps:
    1. Build OperationPool with 3 ai-town handlers + tier-routed LLM clients.
    2. Build DialogueService for protag-protag conversations.
    3. Inject services into every AgentRuntime; flip
       use_aitown_decision_tree=True for protagonists.
    4. Inject lane cove data: shared_memories (protag), life_history
       (protag, LLM batch), social_priors (everyone, via SocialGraphService).
    5. Register on_tick_end_async hook → OperationPool.process_pending →
       route OperationResults back to per-agent tick_inputs.

    Returns {dialogue_service, operation_pool, life_history_count, ...}
    for downstream metrics injection.
    """
    import asyncio as _aio
    from synthetic_socio_wind_tunnel.agent.operations.handlers import (
        handle_do_something,
        handle_generate_message,
        handle_remember_conversation,
    )
    from synthetic_socio_wind_tunnel.agent.operations.pool import OperationPool
    from synthetic_socio_wind_tunnel.conversation.dialogue_service import (
        DialogueService,
    )
    from synthetic_socio_wind_tunnel.data_loader import (
        compute_social_priors_for_population,
        generate_life_history_for_protagonists,
        inject_life_history,
        inject_shared_memories_for_protagonists,
        load_archetypes,
        load_shared_memories,
        load_social_prior_rules,
    )

    print("[aitown] wiring stack...", file=sys.stderr)

    # 0. Augment the existing MemoryService with ai-town aux services so
    # reflection / importance / aitown retrieval mode actually fire.
    from synthetic_socio_wind_tunnel.memory.embedding import NullEmbedding
    from synthetic_socio_wind_tunnel.memory.embeddings_cache import EmbeddingsCache
    from synthetic_socio_wind_tunnel.memory.importance import ImportanceScorer
    from synthetic_socio_wind_tunnel.memory.reflection import ReflectionService
    from synthetic_socio_wind_tunnel.memory.retrieval import MemoryRetriever

    importance_llm = tier_clients.get("nano") or next(iter(tier_clients.values()))
    reflection_llm = tier_clients.get("haiku") or next(iter(tier_clients.values()))
    importance_scorer = ImportanceScorer(llm_client=importance_llm)
    embeddings_cache = EmbeddingsCache(NullEmbedding())
    reflection_service = ReflectionService(
        llm_client=reflection_llm,
        importance_scorer=importance_scorer,
        embeddings_cache=embeddings_cache,
    )
    # Set the private attrs directly — slots prevent dynamic attrs but
    # these particular slots exist on MemoryService already.
    memory_service._importance_scorer = importance_scorer
    memory_service._reflection_service = reflection_service
    memory_service._embeddings_cache = embeddings_cache
    # protag set
    protag_ids = {
        rt.profile.agent_id for rt in runtimes if rt.profile.is_protagonist
    }
    memory_service._protagonist_ids = protag_ids
    # Switch retriever to aitown mode (1:1 normalize-then-sum)
    memory_service._retriever = MemoryRetriever(mode="aitown")

    # 1. OperationPool
    # 2026-05-17 speed optimization: route generate_message off DeepSeek
    # sonnet (v4-pro, slow + expensive) onto Volces Doubao Seed Lite. The
    # dialogue-line generation is ~69% of ops/day in this aitown setup
    # (3175/4628 in preflight). Splitting it onto Volces' independent quota
    # avoids competing with do_something (kept on DeepSeek sonnet) and uses
    # Doubao's fast/cheap generation. Fallback chain:
    #   1st: Volces Doubao Seed Lite (preferred, user-added 2026-05-17)
    #   2nd: Gemini 3.1 Flash Lite (if Volces auth/build fails)
    #   3rd: deepseek-haiku (if both above fail)
    from tools.tier_llm_factory import build_tier_clients as _build_tc
    _gen_msg_tier = None
    try:
        volces_tier_clients = _build_tc(provider="volces")
        tier_clients["doubao_flash"] = volces_tier_clients["haiku"]
        _gen_msg_tier = "doubao_flash"
        print(
            "[aitown] generate_message routed to Volces Doubao Seed Lite "
            "(off DeepSeek sonnet queue)",
            file=sys.stderr,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"[aitown] WARN: Volces Doubao unavailable ({exc!r}); "
            f"trying Gemini Flash Lite",
            file=sys.stderr,
        )
        try:
            gemini_tier_clients = _build_tc(provider="gemini")
            tier_clients["gemini_flash"] = gemini_tier_clients["haiku"]
            _gen_msg_tier = "gemini_flash"
            print(
                "[aitown] generate_message routed to Gemini 3.1 Flash Lite "
                "(Volces fallback)",
                file=sys.stderr,
            )
        except Exception as exc2:  # noqa: BLE001
            print(
                f"[aitown] WARN: Gemini Flash Lite also unavailable ({exc2!r}); "
                f"falling back to deepseek haiku for generate_message",
                file=sys.stderr,
            )
            _gen_msg_tier = "haiku"

    pool = OperationPool(
        handlers={
            "do_something": handle_do_something,
            "generate_message": handle_generate_message,
            "remember_conversation": handle_remember_conversation,
        },
        llm_clients=tier_clients,
        tier_for_kind={
            "do_something": "sonnet",        # DeepSeek v4-pro — decision quality
            "generate_message": _gen_msg_tier,  # Gemini Flash Lite (or haiku fallback)
            "remember_conversation": "haiku",  # DeepSeek v4-flash — short summary
            "reflect": "haiku",
            "score_importance": "nano",
        },
    )

    # 2. DialogueService — single instance per seed run
    dialogue_service = DialogueService(seed=seed)

    # 3. Inject services into runtimes; flip flag for protag.
    profiles = [rt.profile for rt in runtimes]
    for rt in runtimes:
        rt.dialogue_service = dialogue_service
        rt.operation_pool = pool
        rt.memory_service = memory_service
        if rt.profile.is_protagonist:
            rt.use_aitown_decision_tree = True

    # 4a. shared_memories — protag only
    archs = load_archetypes()
    try:
        shared_recs = load_shared_memories()
        injected_shared = inject_shared_memories_for_protagonists(
            profiles, shared_recs, memory_service=memory_service,
        )
        shared_total = sum(injected_shared.values())
        print(
            f"[aitown] shared_memories: {shared_total} events across "
            f"{len(injected_shared)} protag",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"[aitown] shared_memories injection failed: {exc!r}", file=sys.stderr)
        shared_total = 0

    # 4b. life_history + identity_text — setup-content-cache 2026-05-16
    # Single call to _load_or_generate_setup_content: cache HIT = zero LLM,
    # cache MISS = inline generation + persist. Identity text from cache
    # also overwrites profile.identity_text so downstream conversation
    # prompts get the cached persona.
    history_total = 0
    setup_cache_hit = False
    try:
        setup_llm = tier_clients.get("sonnet") or tier_clients.get("haiku") \
            or next(iter(tier_clients.values()))
        history_records, identity_text_map, setup_cache_hit = _aio.run(
            _load_or_generate_setup_content(
                seed=seed,
                profiles=profiles,
                llm_client=setup_llm,
                archetypes=archs,
                n_records_per_protag=20,
                batch_size=4,
                tier="sonnet",
                prompt_version="v2",
            )
        )
        for agent_id, recs in history_records.items():
            history_total += inject_life_history(
                agent_id, recs,
                memory_service=memory_service,
                sim_start_time=sim_start_time,
            )
        # Inject cached identity_text into profile.
        # AgentProfile is Pydantic frozen — must use model_copy(update=...)
        # rather than direct attribute set. The cached identity_text always
        # wins over sample_population's haiku-tier inline variation (which
        # we now skip via protag_llm_variation=False anyway, but template-
        # filled string may still be present and need replacement).
        identity_injected = 0
        for rt in runtimes:
            cached_id = identity_text_map.get(rt.profile.agent_id)
            if cached_id:
                rt.profile = rt.profile.model_copy(
                    update={"identity_text": cached_id},
                )
                identity_injected += 1
        print(
            f"[aitown] life_history: {history_total} events across "
            f"{len(history_records)} protag "
            f"(setup_cache={'HIT' if setup_cache_hit else 'MISS'}, "
            f"identity_text injected={identity_injected})",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"[aitown] life_history injection failed: {exc!r}", file=sys.stderr)

    # 4c. social_priors — everyone
    priors_total = 0
    try:
        rules = load_social_prior_rules()
        priors = compute_social_priors_for_population(
            profiles, rules=rules, archetypes=archs, seed=seed,
        )
        priors_total = social_graph.preload_ties(priors)
        print(
            f"[aitown] social_priors: {priors_total} unique ties preloaded "
            f"(from {len(priors)} prior records)",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"[aitown] social_priors injection failed: {exc!r}", file=sys.stderr)

    # 5. Register sync on_tick_end hook for auto-inviting protag-protag
    #    dialogues. Without this, protag never enter dialogue branch
    #    because scripted_plan keeps branch 6 from firing → do_something
    #    never runs → no LLM dialogue.
    #
    #    Rule: when 2 protag encounter physically AND neither in active
    #    dialogue AND each has 6+ sim-hour cooldown since last dialogue
    #    ended → schedule_invite directly (skip do_something LLM).
    agents_by_id = {rt.profile.agent_id: rt for rt in runtimes}
    protag_ids = {rt.profile.agent_id for rt in runtimes if rt.profile.is_protagonist}
    AUTO_INVITE_COOLDOWN_TICKS = 12 * 6  # 6 sim-hours @ 5min/tick = 72 ticks
    AUTO_INVITE_MAX_PER_AGENT_PER_DAY = 3  # cap to keep cost bounded

    # Per-agent counter: agent_id → {day_index: count}
    auto_invite_counts: dict[str, dict[int, int]] = {}

    auto_invite_attempts = {"scheduled": 0, "skipped_active": 0,
                            "skipped_cooldown": 0, "skipped_cap": 0}

    def _auto_invite_hook(tick_result):
        """Trigger dialogues on protag-protag encounters."""
        day_idx = tick_result.day_index
        for enc in tick_result.encounter_candidates:
            a, b = enc.agent_a, enc.agent_b
            if a not in protag_ids or b not in protag_ids:
                continue
            rt_a = agents_by_id[a]
            rt_b = agents_by_id[b]
            # Either side in active dialogue?
            if rt_a.current_dialogue_id or rt_b.current_dialogue_id:
                auto_invite_attempts["skipped_active"] += 1
                continue
            # Cooldown check (per agent) — `continue` not `return` so other
            # eligible pairs in the same tick still get a chance.
            cooldown_ok = True
            for rt in (rt_a, rt_b):
                if rt.last_dialogue_ended_tick is not None:
                    if (tick_result.tick_index - rt.last_dialogue_ended_tick
                            < AUTO_INVITE_COOLDOWN_TICKS):
                        cooldown_ok = False
                        break
            if not cooldown_ok:
                auto_invite_attempts["skipped_cooldown"] += 1
                continue
            # Per-day cap (also `continue` not `return`)
            cap_ok = True
            for aid in (a, b):
                day_counts = auto_invite_counts.setdefault(aid, {})
                if day_counts.get(day_idx, 0) >= AUTO_INVITE_MAX_PER_AGENT_PER_DAY:
                    cap_ok = False
                    break
            if not cap_ok:
                auto_invite_attempts["skipped_cap"] += 1
                continue
            # Pick a target location — first shared location or fallback
            target_loc = (
                enc.shared_locations[0] if enc.shared_locations
                else rt_a.current_location or "shared"
            )
            try:
                d = dialogue_service.schedule_invite(
                    a, b, target_loc,
                    tick=tick_result.tick_index,
                    simulated_time=tick_result.simulated_time,
                )
                # Both agents already at the same location (encounter
                # implies physical co-location); shortcut walking_over.
                dialogue_service.accept_invite(d.dialogue_id, b)
                dialogue_service.advance_to_participating(
                    d.dialogue_id, tick=tick_result.tick_index,
                )
                rt_a.set_dialogue_id(d.dialogue_id)
                rt_b.set_dialogue_id(d.dialogue_id)
                # Bump counters
                auto_invite_counts.setdefault(a, {})[day_idx] = (
                    auto_invite_counts.setdefault(a, {}).get(day_idx, 0) + 1
                )
                auto_invite_counts.setdefault(b, {})[day_idx] = (
                    auto_invite_counts.setdefault(b, {}).get(day_idx, 0) + 1
                )
                auto_invite_attempts["scheduled"] += 1
            except Exception:
                pass

    orchestrator.register_on_tick_end(_auto_invite_hook)
    # Stash for visibility in stats output
    aitown_attempts_ref = auto_invite_attempts

    # 6. Register on_tick_end_async hook for OperationPool.process_pending
    #    + daily-end reflection trigger for protagonists.
    ticks_per_day = orchestrator._ticks_per_day  # type: ignore[attr-defined]
    last_tick_of_day = ticks_per_day - 1  # tick 287 for 5-min ticks

    async def _process_ops_hook(tick_result):
        try:
            results = await pool.process_pending(tick_result.tick_index)
            for result in results:
                rt = agents_by_id.get(result.agent_id)
                if rt is not None:
                    rt.consume_op_result(result)
        except Exception:
            # Logged inside OperationPool; don't abort the sim
            pass

        # Fire daily reflection for every protag on the last tick of each day.
        # 2026-05-18 hotfix: wrap each maybe_reflect call in asyncio.wait_for
        # with a 60s timeout. The reflection path makes LLM calls that aren't
        # protected by OperationPool's 120s wait_for, so a hung httpx
        # connection mid-SSL could deadlock the entire worker indefinitely.
        # D2 attempt 4 hit this exact bug: seed42 hp + seed43 baseline both
        # hung at day-end ticks 1727 and 2879 respectively, no recovery for
        # 40+ min. 60s per protag means worst-case day-end takes 60s × 500
        # protag = 50 min serially — but most return in 5-15s; the cap just
        # bounds the pathological case.
        import asyncio as _asyncio_local
        within_day_tick = tick_result.tick_index % ticks_per_day
        if within_day_tick == last_tick_of_day:
            for rt in runtimes:
                if not rt.profile.is_protagonist:
                    continue
                try:
                    await _asyncio_local.wait_for(
                        memory_service.maybe_reflect(
                            rt.profile.agent_id,
                            rt.profile.name,
                            current_tick=tick_result.tick_index,
                            simulated_time=tick_result.simulated_time,
                            day_index=tick_result.day_index,
                            force_for_day_end=True,
                        ),
                        timeout=60.0,
                    )
                except _asyncio_local.TimeoutError:
                    # Reflection timed out — log and move on; the agent
                    # doesn't get a reflection for this day. Better than
                    # deadlocking the worker.
                    print(
                        f"[aitown] reflect TIMEOUT (60s) for "
                        f"{rt.profile.agent_id}; skipping",
                        file=sys.stderr,
                    )
                except Exception:
                    pass

    orchestrator.register_on_tick_end_async(_process_ops_hook)

    # 7. Wire lazy hint dependencies onto each runtime (D2 attempt-4 fix,
    #    2026-05-17). AgentRuntime.{recent_memory_hint, nearby_hint,
    #    candidate_destinations_hint} are read by _schedule_do_something_op
    #    and _schedule_generate_message_op when building LLM prompts, but
    #    had no writer in the original code. We now populate them lazily
    #    inside AgentRuntime._refresh_prompt_hints — called by both
    #    schedule_* methods right before they build args. That requires
    #    three dependency refs to be on the runtime up-front:
    #      - poi_destinations_static: STATIC across run (set ONCE here)
    #      - runtimes_index: agent_id → AgentRuntime map (shared dict)
    #      - social_graph_ref: for familiar/stranger flag in nearby_hint
    #    Only ~10-20% of protag schedule do_something per tick, so lazy is
    #    ~5x cheaper than a per-tick on_tick_start sweep across all 500.
    _poi_destinations_static: tuple[str, ...] = tuple(
        getattr(pools, "poi_pool", ()) or ()
    )[:10]
    for rt in runtimes:
        rt.poi_destinations_static = _poi_destinations_static
        rt.runtimes_index = agents_by_id
        rt.social_graph_ref = social_graph

    print("[aitown] wired (lazy hint refs attached)", file=sys.stderr)

    return {
        "dialogue_service": dialogue_service,
        "operation_pool": pool,
        "shared_memories_injected": shared_total,
        "life_history_injected": history_total,
        "social_priors_injected": priors_total,
        "auto_invite_attempts": aitown_attempts_ref,
    }


def run_seed_with_metrics(
    *,
    seed: int,
    n_agents: int,
    start_date: date,
    num_days: int,
    mode: str,
    variant_name: str,
    phase_days: str,
    use_real_llm: bool = False,
    use_aitown: bool = False,
    aitown_provider: str = "gemini",
    num_protagonists: int = 10,
    output_dir: Path | None = None,
    resume_from: int = 0,
    install_hotfix_handler: bool = False,
    restore_from: Any = None,
) -> tuple[MultiDayResult, RunMetrics, dict]:
    """单个 seed 的 metrics-enabled run；返回 (result, run_metrics, variant_metadata).

    suite-wiring change 补：在 orchestrator 栈里接入 MemoryService + Planner +
    StubReplanLLM，让 variants 真的能通过 attention → memory → replan 改变
    agent 行为。
    """
    rng = random.Random(seed)
    atlas = create_atlas_from_osm()
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())

    # wire-instrumentation-stubs (2026-05-20): SETUP_START phase emit.
    # Captures atlas-load → pools → variant-build → aitown-wire as one
    # bracket (the whole pre-run_multi_day setup phase).
    #
    # Default INSTRUMENTATION_OUTPUT_DIR to this cell's variant dir
    # so JSONL files land next to snapshot/WAL (where users expect).
    # Caller can override via env if they want elsewhere.
    if output_dir is not None and not os.environ.get(
        "INSTRUMENTATION_OUTPUT_DIR",
    ):
        os.environ["INSTRUMENTATION_OUTPUT_DIR"] = str(output_dir)
    if not os.environ.get("INSTRUMENTATION_SEED"):
        os.environ["INSTRUMENTATION_SEED"] = str(seed)

    try:
        from synthetic_socio_wind_tunnel.observability import (
            get_instrumentation as _gi_setup,
        )
        from synthetic_socio_wind_tunnel.observability.instrumentation import (
            _read_current_rss_mb as _rss_setup,
        )
        _setup_inst = _gi_setup()
        _setup_rss_before, _ = _rss_setup()
        _setup_inst.emit_event(
            kind="PHASE", phase="SETUP_START",
            seed=seed, variant=variant_name, agents=n_agents,
        )
    except Exception:  # noqa: BLE001
        _setup_inst = None
        _setup_rss_before = 0
    import time as _t_setup
    _setup_t0 = _t_setup.monotonic()

    # fix-population-uses-typed-locations + fix-realism-systemic-gaps: typed
    # pools (with PoolQuotas) replace single-pool outdoor-only destinations.
    # PoolQuotas guarantees food_drink / shop / leisure minimums and balances
    # work_pool across office/school/commercial. n_agents scales pool sizes
    # so 1000-agent runs don't share 20 workplaces.
    from synthetic_socio_wind_tunnel.agent import build_location_pools
    pools = build_location_pools(
        atlas,
        home_count=max(40, n_agents // 2),
        n_agents=n_agents,
        rng=rng,
    )
    target_location = pools.pick_target_location(
        atlas, rng, prefer="community",
    )
    # Provide poi_pool as `destinations` view for any internal call sites that
    # haven't yet migrated. Stub LLM consumes `pools` directly below.
    destinations = list(pools.poi_pool)

    variant, controller = _build_variant(
        variant_name, phase_days, target_location=target_location,
    )

    # 人群采样 — 当 use_aitown 时一并跑 generate_identity=True 让 protag 拿到
    # archetype-grounded identity_text/plan_text。
    profile_template = LANE_COVE_PROFILE.model_copy(update={
        "name": "variant_suite",
        "size": n_agents,
    })
    # backlog 1.7 H (2026-05-20): cached_sample_population caches the
    # deterministic 10-20s sample_population output to disk keyed by
    # (seed, profile, pools, atlas). Subsequent spawns with the same
    # inputs HIT the cache and skip the work. `POPULATION_CACHE_DISABLE=1`
    # to bypass. Safe vs build_location_pools (which we don't cache —
    # see population_cache.py docstring for the rng-determinism reason).
    from synthetic_socio_wind_tunnel.data_loader.population_cache import (
        cached_sample_population,
    )
    if use_aitown:
        # Build tier_clients now (needed downstream for OperationPool +
        # _load_or_generate_setup_content's MISS fallback). identity_llm
        # is no longer needed for sample_population (skipping LLM variation —
        # cache overwrites; see protag_llm_variation=False below).
        from tools.tier_llm_factory import build_tier_clients
        tier_clients = build_tier_clients(provider=aitown_provider)
        profiles = cached_sample_population(
            profile_template,
            seed=seed,
            pools=pools,
            atlas=atlas,
            num_protagonists=num_protagonists,
            generate_identity=True,
            # 2026-05-17 fix: skip the 500-protag haiku identity burst.
            # setup-content-cache provides higher-quality sonnet-tier
            # identity_text that ALWAYS overwrites profile.identity_text
            # on the cache HIT path; on MISS, _load_or_generate_setup_content
            # generates inline at sonnet tier. Either way, the haiku
            # variation step here was pure waste (~$0.5/seed × 10 = $5).
            protag_llm_variation=False,
        )
    else:
        tier_clients = None
        profiles = cached_sample_population(
            profile_template,
            seed=seed,
            pools=pools,
            atlas=atlas,
        )

    adapter: VariantRunnerAdapter | None = None
    if variant is not None:
        adapter = VariantRunnerAdapter(variant, controller, seed=seed)
        profiles = adapter.setup_run(profiles, random.Random(seed + 13))

    # 初始化 runtime + Ledger entities + scripted plan
    runtimes: list[AgentRuntime] = []
    for p in profiles:
        home_loc = p.home_location or (rng.choice(pools.home_pool)
                                       if pools.home_pool else "unknown")
        ledger.set_entity(EntityState(
            entity_id=p.agent_id,
            position=Coord(x=0.0, y=0.0),
            location_id=home_loc,
        ))
        runtime = AgentRuntime(profile=p, current_location=home_loc)
        runtime.plan = build_scripted_plan(
            p, date=start_date.isoformat(), rng=rng, pools=pools, atlas=atlas,
        )
        runtimes.append(runtime)

    attention_service = AttentionService(ledger=ledger, seed=seed)
    # add-attention-induced-nearby-blindness: register per-agent phone_attention
    # baseline (ambient screen-time fraction) + cache personality.openness for
    # notification delta computation. Without this, all agents share the
    # default 0.0 baseline and 0.5 openness fallback.
    from synthetic_socio_wind_tunnel.attention.noticing import baseline_screen_share
    for p in profiles:
        attention_service.set_phone_attention_baseline(
            p.agent_id, baseline_screen_share(p.digital),
        )
        attention_service.set_personality_openness(
            p.agent_id, p.personality.openness,
        )
        # Cache digital profile for delta computation (responsiveness)
        attention_service.set_profile(p.agent_id, p.digital)
    orchestrator = Orchestrator(
        atlas, ledger, runtimes,
        attention_service=attention_service,
        tick_minutes=5, seed=seed,
    )

    # social-graph-capability: 一个 service 实例服务整个 seed run；
    # MemoryService + recorder + 每个 AgentRuntime 共享同一引用
    from synthetic_socio_wind_tunnel.social_graph import SocialGraphService
    social_graph = SocialGraphService(K=10)
    for rt in runtimes:
        rt.social_graph = social_graph

    # conversation-capability：信息流动层；同 seed 内的 service 实例由
    # MemoryService + recorder 共享。seed 用于概率门 reproducibility lock。
    # push-content-individualization：注入 relevance + audience providers，让
    # share 概率公式 + target_precision metric 跟 push 内容个体化对齐
    from synthetic_socio_wind_tunnel.conversation import ConversationService
    from synthetic_socio_wind_tunnel.policy_hack import (
        PushPersonalizer, PUSH_TEMPLATES,
    )
    profile_by_id = {r.profile.agent_id: r.profile for r in runtimes}
    # info_id → template_id mapping built lazily as origins are recorded.
    # Service-side providers look up profile/template each time.
    _topic_to_template: dict[str, str] = {
        f"info_{t.topic_id}": t.template_id for t in PUSH_TEMPLATES
    }
    _template_by_id: dict[str, "PushTemplate"] = {
        t.template_id: t for t in PUSH_TEMPLATES
    }

    def _relevance_provider(info_id: str, agent_id: str) -> float:
        template_id = _topic_to_template.get(info_id)
        if template_id is None:
            return 1.0  # non-personalized push falls through
        template = _template_by_id.get(template_id)
        profile = profile_by_id.get(agent_id)
        if template is None or profile is None:
            return 1.0
        return PushPersonalizer.relevance(profile, template)

    def _audience_tag_provider(agent_id: str) -> str:
        profile = profile_by_id.get(agent_id)
        if profile is None:
            return "default"
        return PushPersonalizer.audience_tag_for(profile)

    conversation = ConversationService(
        seed=seed,
        relevance_provider=_relevance_provider,
        audience_tag_provider=_audience_tag_provider,
    )

    # 挂 metrics recorder — ai-town refs (dialogue_service, memory_service,
    # operation_pool) are set later after _setup_aitown_stack runs.
    recorder = TickMetricsRecorder(
        ledger=ledger,
        attention_service=attention_service,
        social_graph=social_graph,
        conversation=conversation,
    )
    orchestrator.register_on_tick_end(recorder.on_tick_end)

    # add-per-tick-position-logging: capture sparse agent position-change
    # events for 3D dashboard time-slider replay. Written to a separate
    # seed_<N>_positions.json file to keep the main metrics JSON lean.
    from synthetic_socio_wind_tunnel.metrics import PositionTraceRecorder
    position_recorder = PositionTraceRecorder()
    orchestrator.register_on_tick_end(position_recorder.on_tick_end)

    # --- suite-wiring: Memory + Planner + StubReplanLLM ---
    # fix-population-uses-typed-locations: shared_loc 从 poi_pool 选 community
    # heuristic，避免回退到 street；pools 全程传入 stub。
    shared_loc = _pick_community_location(
        atlas, tuple(destinations), poi_pool=pools.poi_pool,
    )
    llm_client = make_llm_client(
        use_real=use_real_llm,
        variant_name=variant_name,
        seed=seed,
        target_location=target_location,
        shared_location=shared_loc,
        atlas=atlas,
        destinations=tuple(destinations),
        pools=pools,
    )
    planner = Planner(llm_client=llm_client)
    # realism-attention-rebalance：seed + atlas 给 should_replan 的概率门 +
    # location_kind 装配。seed=None 时 should_replan 走 module-level random，
    # 行为不 reproducible — 本 suite 显式传 seed 保证 lock。
    memory = MemoryService(
        attention_service=attention_service,
        atlas=atlas,
        seed=seed,
        social_graph=social_graph,
        conversation=conversation,
    )

    agents_by_id = {r.profile.agent_id: r for r in runtimes}

    # 跨 day 累加 replan 计数（B7 fix: 拆 plan-changed vs no-op）
    replan_counter = {
        "total": 0, "by_day": [0] * num_days,
        "no_op_total": 0, "no_op_by_day": [0] * num_days,
    }
    current_day_ref = {"idx": 0}

    def _memory_hook(tr) -> None:
        replans = memory.process_tick(tr, agents_by_id, planner)
        n = len(replans)
        replan_counter["total"] += n
        d = tr.day_index
        if 0 <= d < num_days:
            replan_counter["by_day"][d] += n
            # no_op_today 是 cumulative per day（process_tick 内部跨日 reset）；
            # 取每 tick 之后的 max 值就能在 day 末尾保留 day 总和。
            no_op_today = memory.replan_no_op_count_today_total()
            current = replan_counter["no_op_by_day"][d]
            replan_counter["no_op_by_day"][d] = max(current, no_op_today)
        current_day_ref["idx"] = d

    orchestrator.register_on_tick_end(_memory_hook)

    # ai-town port wiring (Stage 4) — after memory + social_graph + conversation
    # are built, so we can attach DialogueService + OperationPool + lane cove
    # data to the runtimes and orchestrator.
    aitown_stats: dict = {}
    if use_aitown:
        aitown_stats = _setup_aitown_stack(
            orchestrator=orchestrator,
            runtimes=runtimes,
            memory_service=memory,
            social_graph=social_graph,
            tier_clients=tier_clients,
            seed=seed,
            sim_start_time=ledger.current_time,
            pools=pools,
        )
        # Wire ai-town service refs into recorder so build_run_metrics
        # picks up reflection_count / dialogue_count / op stats.
        recorder.attach_aitown_services(
            dialogue_service=aitown_stats["dialogue_service"],
            memory_service=memory,
            operation_pool=aitown_stats["operation_pool"],
        )

        # Print auto-invite stats AFTER run finishes (post-hoc)
        def _print_invite_stats(_summary) -> None:
            attempts = aitown_stats["auto_invite_attempts"]
            print(
                f"[aitown] auto_invite: scheduled={attempts['scheduled']}, "
                f"skipped_active={attempts['skipped_active']}, "
                f"skipped_cooldown={attempts['skipped_cooldown']}, "
                f"skipped_cap={attempts['skipped_cap']}",
                file=sys.stderr,
            )
        orchestrator.register_on_simulation_end(_print_invite_stats)

    # run-resilience: write per-day partial JSON next to seed_<N>.json so
    # SIGKILL / SIGUSR1 / crash mid-run loses ≤ 1 simulation day.
    # `provider_name` is recorded in partial metadata so resume can verify
    # provider consistency.
    if use_aitown:
        _provider_name = aitown_provider
    elif use_real_llm:
        _provider_name = "anthropic"
    else:
        _provider_name = "stub"

    runner = MultiDayRunner(
        orchestrator=orchestrator,
        memory_service=memory,  # ← 2026-05-19 hotfix: was missing, caused
                                # snapshot.memory_store_state to be empty {}.
                                # D2 attempt 4 dialogue/memory content lost.
        seed=seed,
        mode=mode,  # type: ignore[arg-type]
        output_dir=output_dir,
        resume_from=resume_from,
        provider_name=_provider_name,
        # tick-level-resume (2026-05-16)
        attention_service=attention_service,
        restore_from=restore_from,
        # capability 1.11 (2026-05-19): preserve per-day metric buckets
        # across kill+resume so seed_X.json reflects ALL days run.
        tick_metrics_recorder=recorder,
        # capability 1.12 (2026-05-19): preserve dialogue + DialogueMessage
        # content across kill+resume. Without this, agent narrative output
        # ("agent 之间的故事") is lost. Only present when ai-town stack
        # is wired (smoke/non-aitown runs don't have a DialogueService).
        dialogue_service=aitown_stats.get("dialogue_service") if use_aitown else None,
    )

    # run-resilience: register SIGUSR1 graceful-stop handler if caller asked
    # for it. Caller (main loop) sets install_hotfix_handler=True; tests pass
    # False to avoid touching global signal state.
    _hotfix_installed = False
    if install_hotfix_handler:
        from synthetic_socio_wind_tunnel.run_resilience import HotfixSignalHandler
        _hotfix = HotfixSignalHandler()
        _hotfix.install(runner)
        _hotfix_installed = True

    if adapter is not None:
        adapter.attach_to(runner)

    # on_day_start: scripted plan reset + variant hook
    def _on_day_start(current_date: date, day_index: int) -> None:
        local_rng = random.Random(seed + day_index)
        for rt in runtimes:
            rt.plan = build_scripted_plan(
                rt.profile, date=current_date.isoformat(),
                rng=local_rng, pools=pools, atlas=atlas,
            )
            home = rt.profile.home_location or rt.current_location
            ent = ledger.get_entity(rt.profile.agent_id)
            if ent is not None:
                ledger.set_entity(EntityState(
                    entity_id=ent.entity_id,
                    position=Coord(x=0.0, y=0.0),
                    location_id=home,
                ))
            rt.current_location = home
            rt.cancel_movement()
        if adapter is not None:
            adapter.on_day_start(current_date, day_index)

    # wire-instrumentation-stubs: SETUP_DONE emit before tick loop starts
    try:
        if _setup_inst is not None:
            _rss_after, _ = _rss_setup()
            _setup_inst.emit_event(
                kind="PHASE", phase="SETUP_DONE",
                duration_sec=_t_setup.monotonic() - _setup_t0,
                rss_before_mb=_setup_rss_before,
                rss_after_mb=_rss_after,
            )
    except Exception:  # noqa: BLE001
        pass

    result = runner.run_multi_day(
        start_date=start_date, num_days=num_days,
        on_day_start=_on_day_start,
    )

    if adapter is not None:
        adapter.augment_result_metadata(result)

    # ai-town: inspect final dialogue state for debugging
    if use_aitown and aitown_stats:
        dsvc = aitown_stats["dialogue_service"]
        pool_ref = aitown_stats["operation_pool"]
        all_d = dsvc.all_dialogues()
        active = [d for d in all_d if d.ended_tick is None]
        ended = [d for d in all_d if d.ended_tick is not None]
        msg_counts_active = [d.message_count() for d in active]
        msg_counts_ended = [d.message_count() for d in ended]
        print(
            f"[aitown] dialogue stats — total={len(all_d)} "
            f"active={len(active)} ended={len(ended)}",
            file=sys.stderr,
        )
        if msg_counts_active:
            print(
                f"[aitown]   active msg counts: {msg_counts_active}",
                file=sys.stderr,
            )
        if msg_counts_ended:
            print(
                f"[aitown]   ended msg counts: {msg_counts_ended} "
                f"reasons: {dsvc.counts_by_end_reason()}",
                file=sys.stderr,
            )
        # Op pool stats
        completed = pool_ref._completed_log
        errors = pool_ref._error_log
        kinds = {}
        for r in completed:
            kinds[r.kind] = kinds.get(r.kind, 0) + 1
        print(
            f"[aitown] op stats — completed={len(completed)} "
            f"errors={len(errors)} by_kind={kinds}",
            file=sys.stderr,
        )
        if errors:
            for r in errors[:3]:
                print(
                    f"[aitown]   error sample: {r.kind} {r.error_msg}",
                    file=sys.stderr,
                )

    # 组装 RunMetrics
    variant_metadata = variant.metadata_dict() if variant else {"name": "baseline"}
    # 注入 target_location 供 factory 用
    if variant_name in {"hyperlocal_push", "global_distraction"} and target_location:
        variant_metadata = dict(variant_metadata)
        variant_metadata["target_location"] = target_location

    run_metrics = build_run_metrics(
        recorder,
        multi_day_result=result,
        atlas=atlas,
        variant_name=variant_name,
        variant_metadata=variant_metadata,
        phase_config=controller.model_dump(),
    )

    # suite-wiring: replan counters → RunMetrics.extensions (B7 fix split)
    no_op_total = sum(replan_counter["no_op_by_day"])
    run_metrics = run_metrics.with_extensions(
        replan_count=replan_counter["total"],
        replan_by_day=list(replan_counter["by_day"]),
        replan_no_op_count=no_op_total,
        replan_no_op_by_day=list(replan_counter["no_op_by_day"]),
    )

    # backlog 1.13 第二阶段: surface per-day LLM fallback% so aggregate
    # can flag "silent disaster" variants.
    if result.per_day_summaries:
        max_fb = max(d.llm_fallback_pct for d in result.per_day_summaries)
        avg_fb = sum(d.llm_fallback_pct for d in result.per_day_summaries) / len(
            result.per_day_summaries,
        )
        aks_open_total = sum(d.all_keys_open_count for d in result.per_day_summaries)
    else:
        max_fb = 0.0
        avg_fb = 0.0
        aks_open_total = 0
    run_metrics = run_metrics.with_extensions(
        max_llm_fallback_pct=max_fb,
        avg_llm_fallback_pct=avg_fb,
        all_keys_open_total=aks_open_total,
    )

    # publishable-finalize: stamp 7-field reproducibility lock
    from synthetic_socio_wind_tunnel.metrics.reproducibility import (
        compute_reproducibility_lock,
    )
    # B10 fix: thread provider through so rep_lock.model_version reflects
    # the actual LLM used. Order of precedence:
    #   use_aitown=True  → aitown_provider drives both ai-town stack + identity
    #   use_real_llm=True (without aitown) → anthropic for planner.replan
    #   else → stub
    if use_aitown:
        effective_provider = aitown_provider
    elif use_real_llm:
        effective_provider = "anthropic"
    else:
        effective_provider = "stub"
    rep_lock = compute_reproducibility_lock(
        seed_pool=[seed],
        use_real_llm=use_real_llm,
        variant_names=[variant_name],
        phase_config=_parse_phase_days_to_dict(phase_days),
        provider=effective_provider,
    )
    run_metrics = run_metrics.with_extensions(reproducibility_lock=rep_lock)

    # add-per-tick-position-logging: stash recorder for caller-side
    # serialization next to the seed JSON file.
    variant_metadata["position_recorder"] = position_recorder

    return result, run_metrics, variant_metadata


def main() -> int:
    args = parse_args()
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    unknown = [v for v in variants if v not in _KNOWN_VARIANTS]
    if unknown:
        print(f"[error] unknown variants: {unknown}", file=sys.stderr)
        print(f"[error] known: {_KNOWN_VARIANTS}", file=sys.stderr)
        return 2

    start_date = date.fromisoformat(args.start_date)
    if args.suite_dir is not None:
        suite_dir = args.suite_dir
        if args.resume and not suite_dir.exists():
            print(f"[suite] --resume specified but --suite-dir {suite_dir} "
                  f"does not exist; nothing to resume from", file=sys.stderr)
            return 2
        suite_dir.mkdir(parents=True, exist_ok=True)
        if args.resume:
            print(f"[suite] RESUME mode — existing seed_*.json will be "
                  f"loaded from disk instead of re-run")
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suite_dir = args.output_dir / f"{ts}_{args.suite_name}"
        suite_dir.mkdir(parents=True, exist_ok=True)

    print(f"[suite] {args.suite_name} | variants={variants} | "
          f"seeds={args.seeds} × days={args.num_days} | mode={args.mode}")
    print(f"[suite] output → {suite_dir}")

    # run-resilience: publishable preflight gate.
    # Definition of "publishable mode" for this gate: agents == 1000
    # AND num_days == 14 (matches CLAUDE.md canon). When triggered:
    # always invoke tools/preflight_full_smoke.py; --skip-preflight is
    # IGNORED with a stderr warning (the D1' scale-only-bug lesson).
    # Skipped when we are already inside a worker subprocess (suite_dir
    # explicitly passed by parent + --workers==1) to avoid recursion.
    _is_publishable = args.agents == 1000 and args.num_days == 14
    _is_worker_child = args.suite_dir is not None and args.workers == 1

    # enforce-worker-rss-cap (2026-05-19): publishable mode SHALL cap
    # per-worker RSS. 2026-05-19 D2 incident: single workers reached
    # 16-37GB RSS sawtooth on a 48GB machine — one bloat from snapshot
    # parsing pushed the kernel into swap and pages flushed. Hard cap
    # at 10GB; combined with cold-prune encounter eviction + malloc
    # pressure relief, this keeps workers well under jetsam pressure
    # and lets resume_publishable.py auto-restart bloated workers
    # via existing graceful_stop path.
    #
    # Override allowed via explicit env (tests, dev). Worker children
    # inherit from parent, so we set it for both _is_worker_child and
    # parent: any unset env -> 10000.
    if _is_publishable and not os.environ.get("RSS_RESTART_MB"):
        os.environ["RSS_RESTART_MB"] = "10000"
        if not _is_worker_child:
            print(
                "[suite] publishable mode: defaulting RSS_RESTART_MB=10000 "
                "(per-worker 10GB hard cap; override via env to opt out)",
                file=sys.stderr,
            )
    # 2026-05-17 escape hatch: when relaunching D2 after we've already
    # successfully passed preflight earlier today on identical code state,
    # the 2-hour publishable preflight is pure waste. Set
    # RESILIENCE_TRUST_LAST_PREFLIGHT=1 to skip it. Use ONLY when you
    # know the code hasn't materially changed since last green preflight.
    _trust_preflight = os.environ.get(
        "RESILIENCE_TRUST_LAST_PREFLIGHT", ""
    ).strip().lower() in ("1", "true", "yes")
    if _is_publishable and not _is_worker_child and _trust_preflight:
        print(
            "[suite] RESILIENCE_TRUST_LAST_PREFLIGHT=1 — skipping publishable "
            "preflight (caller asserts last green preflight is still valid). "
            "If code has changed since, abort with Ctrl-C and unset the env.",
            file=sys.stderr,
        )
    if _is_publishable and not _is_worker_child and not _trust_preflight:
        if args.skip_preflight:
            print(
                "[suite] WARN: publishable mode (--agents 1000 --num-days 14) "
                "IGNORES --skip-preflight; running preflight regardless. "
                "(Use RESILIENCE_TRUST_LAST_PREFLIGHT=1 if you've already "
                "passed preflight on this code today.)",
                file=sys.stderr,
            )
        import subprocess as _sp
        repo_root = Path(__file__).resolve().parents[1]
        pre_cmd = [
            sys.executable, str(repo_root / "tools" / "preflight_full_smoke.py"),
        ]
        if args.use_aitown:
            pre_cmd.extend(["--provider", args.aitown_provider])
        else:
            pre_cmd.extend(["--provider", "stub"])
        print(f"[suite] running preflight: {' '.join(pre_cmd)}")
        pre_rc = _sp.call(pre_cmd)
        if pre_rc != 0:
            print(
                f"[suite] PREFLIGHT FAILED (rc={pre_rc}); refusing to start "
                f"publishable run. Investigate with "
                f"tools/audit_run_health.py before retrying.",
                file=sys.stderr,
            )
            return pre_rc
    elif not _is_publishable and args.skip_preflight:
        print("[suite] --skip-preflight noted (non-publishable mode; preflight was not going to run anyway)")

    t0 = time.perf_counter()
    aggregates: dict[str, SuiteAggregate] = {}

    # Process-level parallelism (--workers N > 1): fan out variants across
    # subprocess workers, each writing into the same --suite-dir. Coordinator
    # (this process) blocks until all workers exit, then re-loads aggregates
    # and builds the final contest report. Each worker calls THIS SAME script
    # with --variants <single> --workers 1 --suite-dir <shared> --resume.
    if args.workers > 1 and len(variants) > 1:
        import subprocess as _sp
        from concurrent.futures import ThreadPoolExecutor as _TPE
        n_workers = min(args.workers, len(variants))
        print(f"[suite] worker-pool mode: {n_workers} parallel workers "
              f"× {len(variants)} variants")

        def _run_worker(variant_name: str) -> tuple[str, int, str]:
            worker_log = suite_dir / f"worker_{variant_name}.log"
            cmd = [
                sys.executable, "tools/run_variant_suite.py",
                "--variants", variant_name,
                "--seeds", str(args.seeds),
                "--seed-start", str(args.seed_start),  # inherit base seed
                "--num-days", str(args.num_days),
                "--agents", str(args.agents),
                "--mode", args.mode,
                "--phase-days", args.phase_days,
                "--start-date", args.start_date,
                "--suite-name", args.suite_name,
                "--suite-dir", str(suite_dir),
                "--workers", "1",  # critical: prevent recursion
                "--resume",  # safe by default; skips already-done seeds
            ]
            if args.num_protagonists is not None:
                cmd += ["--num-protagonists", str(args.num_protagonists)]
            if args.use_real_llm:
                cmd += ["--use-real-llm"]
            if args.use_aitown:
                cmd += ["--use-aitown",
                        "--aitown-provider", args.aitown_provider]
            with open(worker_log, "w", encoding="utf-8") as lf:
                # run-resilience: write `pid <child>` header so
                # audit_run_health.py can discover this worker mid-run.
                # We write the header BEFORE Popen; the child's stdout is
                # appended after.
                proc = _sp.Popen(cmd, stdout=lf, stderr=_sp.STDOUT)
                # Stamp pid into the log so audit_run_health.py's
                # _discover_pid (regex `pid \d+` in first 4 KB) finds it.
                # Use a small pids.json companion as the canonical channel
                # (race-free vs. interleaving with child's stdout).
                try:
                    _update_pids_json(suite_dir, variant_name, proc.pid)
                except OSError:
                    pass
                proc.wait()
            return variant_name, proc.returncode, str(worker_log)

        # stagger-worker-spawn (2026-05-19): avoid 4-worker burst that
        # triggered DeepSeek server-side TCP drop in D2 attempt 6. Submit
        # workers with min spacing between subprocess.Popen calls.
        # Override via RESILIENCE_MIN_SPAWN_SPACING_SECS (0 = burst mode).
        _stagger_secs = int(os.environ.get(
            "RESILIENCE_MIN_SPAWN_SPACING_SECS", "300",
        ) or 0)
        if _stagger_secs > 0 and len(variants) > 1:
            print(
                f"[suite] worker-pool stagger: {_stagger_secs}s between "
                f"worker spawns to avoid LLM API burst self-DDoS",
                file=sys.stderr,
            )
        with _TPE(max_workers=n_workers) as pool:
            futures = _staggered_submit(
                pool, _run_worker, variants, spacing_secs=_stagger_secs,
            )
            results = [f.result() for f in futures]
        for v, rc, log in results:
            status = "ok" if rc == 0 else f"FAIL rc={rc}"
            print(f"  worker[{v}]: {status} → {log}")
        # Re-load per-variant aggregates from disk to build the suite contest
        for v in variants:
            agg = suite_dir / f"variant_{v}" / "aggregate.json"
            if agg.exists():
                with open(agg, "r", encoding="utf-8") as f:
                    aggregates[v] = SuiteAggregate.model_validate(json.load(f))
            else:
                print(f"  [warn] {v} aggregate missing — contest will skip it",
                      file=sys.stderr)
        # Skip the per-variant serial loop below
        _skip_serial = True
    else:
        _skip_serial = False

    if not _skip_serial:
      for variant_name in variants:
        variant_dir = suite_dir / f"variant_{variant_name}"
        variant_dir.mkdir(parents=True, exist_ok=True)
        runs: list[RunMetrics] = []
        print(f"\n[variant] {variant_name}")

        # Resume: if this variant's aggregate already exists, skip the whole
        # variant — load aggregate from disk so contest report can still
        # cross-compare.
        agg_file = variant_dir / "aggregate.json"
        if args.resume and agg_file.exists():
            try:
                with open(agg_file, "r", encoding="utf-8") as f:
                    aggregates[variant_name] = SuiteAggregate.model_validate(
                        json.load(f),
                    )
                print(f"  [resumed] aggregate.json exists → variant skipped")
                continue
            except Exception as e:
                print(f"  [resume] failed to load existing aggregate: {e}; "
                      f"falling through to re-run", file=sys.stderr)

        captured_variant_metadata: dict = {"name": variant_name}
        for i in range(args.seeds):
            seed = args.seed_start + i
            seed_file_resume = variant_dir / f"seed_{seed}.json"
            # Resume: if seed file exists, load run_metrics back from disk
            # rather than re-running the (expensive) seed.
            if args.resume and seed_file_resume.exists():
                try:
                    with open(seed_file_resume, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    resumed_rm = RunMetrics.model_validate(d["run_metrics"])
                    runs.append(resumed_rm)
                    print(f"  seed={seed} [resumed from "
                          f"{seed_file_resume.name}]")
                    continue
                except Exception as e:
                    print(f"  [resume] seed_{seed}.json load failed: {e}; "
                          f"re-running", file=sys.stderr)
            t_s = time.perf_counter()
            # A2 fix: --num-protagonists CLI; default 10% of agents
            n_protag = (
                args.num_protagonists
                if args.num_protagonists is not None
                else max(1, args.agents // 10)
            )

            # tick-level-resume + run-resilience: 4-strategy resume detection.
            #
            #   none         → fresh start (effective_resume_from=0, restore_from=None)
            #   snapshot-only→ require snapshot; fail-fast if missing
            #   partial-only → ignore snapshots, use per-day partial only
            #   auto         → snapshot priority, partial fallback (default)
            #
            # --resume-from-day overrides effective_resume_from regardless of strategy.
            effective_resume_from = 0
            restore_from_snap = None
            strategy = args.resume_strategy
            do_resume = args.resume or strategy != "none"

            if strategy == "none":
                do_resume = False
            elif strategy == "auto" and do_resume:
                # Try snapshot first
                from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
                    SimulationCheckpoint, find_latest_snapshot,
                )
                snap_path = find_latest_snapshot(variant_dir, seed=seed)
                if snap_path is not None:
                    try:
                        restore_from_snap = SimulationCheckpoint.read(snap_path)
                        print(
                            f"  seed={seed} [snapshot found at {snap_path.name}, "
                            f"restoring tick_global={restore_from_snap.tick_index} "
                            f"day={restore_from_snap.day_index}]",
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"  [resume] snapshot load failed: {exc}; "
                            f"falling back to per-day partial", file=sys.stderr,
                        )

            if strategy == "snapshot-only" and do_resume:
                from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
                    SimulationCheckpoint, find_latest_snapshot,
                )
                snap_path = find_latest_snapshot(variant_dir, seed=seed)
                if snap_path is None:
                    print(
                        f"  [resume] strategy=snapshot-only but no snapshot found "
                        f"for seed={seed} in {variant_dir}; refusing to proceed",
                        file=sys.stderr,
                    )
                    return 2
                restore_from_snap = SimulationCheckpoint.read(snap_path)

            # Fallback to per-day partial (or strategy=partial-only): use
            # effective_resume_from when restore_from_snap is still None.
            if restore_from_snap is None and do_resume and strategy != "snapshot-only":
                from synthetic_socio_wind_tunnel.run_resilience import (
                    DayCheckpointWriter,
                )
                _ckpt = DayCheckpointWriter()
                latest = _ckpt.find_latest_partial(
                    output_dir=variant_dir, seed=seed,
                )
                if latest is not None:
                    try:
                        payload = _ckpt.read_partial(latest)
                        effective_resume_from = int(payload["day_index"]) + 1
                        print(
                            f"  seed={seed} [partial found at {latest.name}, "
                            f"resuming from day {effective_resume_from}]",
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"  [resume] partial load failed: {exc}; "
                            f"starting from day 0", file=sys.stderr,
                        )

            # CLI override always wins
            if args.resume_from_day is not None:
                effective_resume_from = args.resume_from_day
                restore_from_snap = None  # explicit override → don't restore state

            result, run_metrics, captured_variant_metadata = run_seed_with_metrics(
                seed=seed, n_agents=args.agents, start_date=start_date,
                num_days=args.num_days, mode=args.mode,
                variant_name=variant_name, phase_days=args.phase_days,
                use_real_llm=args.use_real_llm,
                use_aitown=args.use_aitown,
                aitown_provider=args.aitown_provider,
                num_protagonists=n_protag,
                output_dir=variant_dir,
                resume_from=effective_resume_from,
                install_hotfix_handler=True,
                restore_from=restore_from_snap,
            )
            t_e = time.perf_counter()

            # CLAUDE.md `sigusr1-graceful-stop-corruption` invariant:
            # if run exited via SIGUSR1 graceful-stop (memory auto-restart,
            # external kill -USR1, etc.), seed_N.json is NOT the final
            # artifact — partials are. Writing seed_N.json here + running
            # cleanup_partials would mark the cell DONE in audit while
            # the data is truncated, and would delete the per-day partials
            # that resume needs. Skip both writes; resume picks up next.
            graceful_stop = bool(
                (result.metadata or {}).get("graceful_stop", False)
            )

            seed_file = variant_dir / f"seed_{seed}.json"
            pos_file = variant_dir / f"seed_{seed}_positions.json"

            if graceful_stop:
                completed_days = len(result.per_day_summaries)
                print(
                    f"  seed={seed} wall={t_e - t_s:.1f}s "
                    f"GRACEFUL_STOP after {completed_days} day(s) "
                    f"— seed_{seed}.json NOT written, partials preserved "
                    f"for resume"
                )
            else:
                dump = {
                    "multi_day_result": result.model_dump(),
                    "run_metrics": run_metrics.model_dump(),
                }
                with open(seed_file, "w", encoding="utf-8") as f:
                    json.dump(dump, f, ensure_ascii=False, indent=2)

                # add-per-tick-position-logging: write companion position
                # trace for 3D dashboard replay.
                pos_recorder = captured_variant_metadata.pop(
                    "position_recorder", None,
                )
                pos_changes = 0
                if pos_recorder is not None:
                    pos_recorder.write(pos_file)
                    pos_changes = pos_recorder.total_changes
                runs.append(run_metrics)
                print(f"  seed={seed} wall={t_e - t_s:.1f}s "
                      f"encs={result.total_encounters} pos_changes={pos_changes} "
                      f"→ {seed_file.name}")

                # run-resilience: cleanup partial files now that
                # seed_<N>.json has landed (the final artifact is the
                # source of truth).
                try:
                    from synthetic_socio_wind_tunnel.run_resilience import (
                        DayCheckpointWriter,
                    )
                    DayCheckpointWriter().cleanup_partials(
                        output_dir=variant_dir, seed=seed,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"  [warn] partial cleanup failed: {exc}",
                        file=sys.stderr,
                    )

        # aggregate — 用真实跑出来的 variant_metadata（factory 已填 target_location 等）
        aggregate = build_suite_aggregate(runs, variant_metadata=captured_variant_metadata)
        agg_file = variant_dir / "aggregate.json"
        with open(agg_file, "w", encoding="utf-8") as f:
            json.dump(aggregate.model_dump(), f, ensure_ascii=False, indent=2)
        aggregates[variant_name] = aggregate
        print(f"  aggregate → {agg_file.name}")

    # contest
    contest = build_contest_report(aggregates, suite_name=args.suite_name)
    contest_file = suite_dir / "contest.json"
    with open(contest_file, "w", encoding="utf-8") as f:
        json.dump(contest.model_dump(), f, ensure_ascii=False, indent=2)
    print(f"\n[contest] → {contest_file.name}")

    # markdown
    report_file = write_markdown(contest, aggregates, suite_dir)
    print(f"[report] → {report_file}")

    total = time.perf_counter() - t0
    print(f"\n[done] total wall={total:.1f}s | rows={len(contest.rows)}")
    for row in contest.rows:
        eff = f"{row.primary_effect_size:.1f}" if row.primary_effect_size is not None else "N/A"
        print(f"   {row.variant_name:<22} {row.evidence_alignment:<15} eff={eff}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
