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
import json
import random
import sys
import time
from pathlib import Path

# Auto-load <repo>/.env so --use-real-llm picks up GEMINI_API_KEY without
# requiring shell export. Path-jiggling so the import works regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import load_dotenv as _load_dotenv  # noqa: E402
_load_dotenv()
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
    p.add_argument("--workers", type=int, default=1,
                   help="Process-level parallelism: split variants across N "
                        "worker subprocesses, each running ALL seeds for one "
                        "variant against a shared --suite-dir. Coordinator "
                        "process aggregates at the end. Default 1 (serial). "
                        "Pick min(workers, len(variants)).")
    return p.parse_args()


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
    pool = OperationPool(
        handlers={
            "do_something": handle_do_something,
            "generate_message": handle_generate_message,
            "remember_conversation": handle_remember_conversation,
        },
        llm_clients=tier_clients,
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

    # 4b. life_history — LLM batch for protag (uses haiku tier)
    history_total = 0
    try:
        life_llm = tier_clients.get("haiku") or next(iter(tier_clients.values()))
        history_records = _aio.run(
            generate_life_history_for_protagonists(
                profiles, llm_client=life_llm, archetypes=archs,
                n_records_per_protag=10, batch_size=5,
            )
        )
        for agent_id, recs in history_records.items():
            history_total += inject_life_history(
                agent_id, recs,
                memory_service=memory_service,
                sim_start_time=sim_start_time,
            )
        print(
            f"[aitown] life_history: {history_total} events across "
            f"{len(history_records)} protag",
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
        within_day_tick = tick_result.tick_index % ticks_per_day
        if within_day_tick == last_tick_of_day:
            for rt in runtimes:
                if not rt.profile.is_protagonist:
                    continue
                try:
                    await memory_service.maybe_reflect(
                        rt.profile.agent_id,
                        rt.profile.name,
                        current_tick=tick_result.tick_index,
                        simulated_time=tick_result.simulated_time,
                        day_index=tick_result.day_index,
                        force_for_day_end=True,
                    )
                except Exception:
                    pass

    orchestrator.register_on_tick_end_async(_process_ops_hook)

    print("[aitown] wired", file=sys.stderr)

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
    if use_aitown:
        # Build a shared LLM client for identity generation (and later ai-town ops)
        from tools.tier_llm_factory import build_tier_clients
        tier_clients = build_tier_clients(provider=aitown_provider)
        identity_llm = tier_clients.get("haiku") or next(iter(tier_clients.values()))
        profiles = sample_population(
            profile_template,
            seed=seed,
            pools=pools,
            atlas=atlas,
            num_protagonists=num_protagonists,
            generate_identity=True,
            llm_client=identity_llm,
        )
    else:
        tier_clients = None
        profiles = sample_population(
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

    runner = MultiDayRunner(
        orchestrator=orchestrator,
        seed=seed,
        mode=mode,  # type: ignore[arg-type]
    )
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
                proc = _sp.run(cmd, stdout=lf, stderr=_sp.STDOUT)
            return variant_name, proc.returncode, str(worker_log)

        with _TPE(max_workers=n_workers) as pool:
            results = list(pool.map(_run_worker, variants))
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
            seed = 42 + i
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
            result, run_metrics, captured_variant_metadata = run_seed_with_metrics(
                seed=seed, n_agents=args.agents, start_date=start_date,
                num_days=args.num_days, mode=args.mode,
                variant_name=variant_name, phase_days=args.phase_days,
                use_real_llm=args.use_real_llm,
                use_aitown=args.use_aitown,
                aitown_provider=args.aitown_provider,
                num_protagonists=n_protag,
            )
            t_e = time.perf_counter()

            # dump per-seed
            seed_file = variant_dir / f"seed_{seed}.json"
            dump = {
                "multi_day_result": result.model_dump(),
                "run_metrics": run_metrics.model_dump(),
            }
            with open(seed_file, "w", encoding="utf-8") as f:
                json.dump(dump, f, ensure_ascii=False, indent=2)

            # add-per-tick-position-logging: write companion position trace
            # for 3D dashboard replay.
            pos_recorder = captured_variant_metadata.pop("position_recorder", None)
            pos_file = variant_dir / f"seed_{seed}_positions.json"
            pos_changes = 0
            if pos_recorder is not None:
                pos_recorder.write(pos_file)
                pos_changes = pos_recorder.total_changes
            runs.append(run_metrics)
            print(f"  seed={seed} wall={t_e - t_s:.1f}s "
                  f"encs={result.total_encounters} pos_changes={pos_changes} "
                  f"→ {seed_file.name}")

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
