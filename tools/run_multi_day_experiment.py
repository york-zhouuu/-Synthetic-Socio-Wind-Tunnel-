#!/usr/bin/env python3
"""
run_multi_day_experiment — 多日 simulation CLI（基建冒烟）

不是实验 variant 的实现（那是 policy-hack change 的事）。本 CLI 只：
- 接受 --variant 作为字符串传参（当前仅 "baseline"）
- 构造 Orchestrator + MultiDayRunner（scripted plan，零 LLM 成本）
- 跑 N seed × N day
- dump 每 seed 一份 JSON + aggregate JSON 到 data/runs/<timestamp>/

Usage:
    python3 tools/run_multi_day_experiment.py \\
        --start-date 2026-04-22 --num-days 14 --agents 100 --seeds 30 \\
        --variant baseline --mode publishable

    python3 tools/run_multi_day_experiment.py \\
        --num-days 3 --agents 10 --seeds 2 --mode dev     # 快速冒烟
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date, datetime
from pathlib import Path

# Reuse helpers from smoke demo to avoid duplicating Lane Cove bootstrap logic
sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_experiment_demo import (  # type: ignore
    build_scripted_plan,
    _pick_connected_destinations,
)

from synthetic_socio_wind_tunnel.agent import (
    AgentRuntime,
    Planner,
    LANE_COVE_PROFILE,
    sample_population,
)
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.lanecove import create_atlas_from_osm
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.attention import AttentionService
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start-date", type=str, default="2026-04-22",
                   help="ISO format YYYY-MM-DD")
    p.add_argument("--num-days", type=int, default=14)
    p.add_argument("--agents", type=int, default=100)
    p.add_argument("--seeds", type=int, default=30,
                   help="Number of seeds to run; each seed is an independent run")
    available = ["baseline"] + sorted(VARIANTS.keys())
    p.add_argument("--variant", type=str, default="baseline",
                   choices=available,
                   help=("Variant name. 'baseline' = no variant applied; "
                         "others dispatch to policy_hack.VARIANTS."))
    p.add_argument("--mode", choices=["dev", "publishable"], default="publishable")
    p.add_argument("--phase-days", type=str, default="4,6,4",
                   help="baseline,intervention,post days (default 4,6,4)")
    p.add_argument("--output-dir", type=Path, default=Path("data/runs"),
                   help="Base dir; per-run timestamp subdir will be created")
    return p.parse_args()


def _build_variant_and_controller(
    variant_name: str,
    phase_days: str,
    target_location: str | None = None,
) -> tuple[Variant | None, PhaseController | None]:
    """解析 variant + phase config；baseline 返回 (None, None)。"""
    if variant_name == "baseline":
        return None, None
    cls = VARIANTS[variant_name]

    kwargs: dict = {}
    if variant_name == "hyperlocal_push" and target_location is not None:
        kwargs["target_location"] = target_location
    # 其它 variant 的默认字段覆盖 run 所需

    variant = cls(**kwargs) if kwargs else cls()

    parts = [int(x.strip()) for x in phase_days.split(",")]
    if len(parts) != 3:
        raise ValueError(f"--phase-days expects 3 ints like '4,6,4'; got {phase_days!r}")
    controller = PhaseController(
        baseline_days=parts[0],
        intervention_days=parts[1],
        post_days=parts[2],
    )
    return variant, controller


def build_single_seed_run(
    *,
    seed: int,
    n_agents: int,
    start_date: date,
    num_days: int,
    mode: str,
    variant_name: str = "baseline",
    phase_days: str = "4,6,4",
) -> MultiDayResult:
    """
    为单个 seed 搭出最小 orchestrator 栈并跑多日。

    若 `variant_name != "baseline"`：
    - 先 `VariantRunnerAdapter.setup_run(profiles, rng)` 改人群（D catalyst
      在此时生效）
    - 构造 orchestrator + attention_service（policy-hack 的 push 变体需要）
    - attach adapter，以其 on_day_start 接力 scripted-plan 重置
    """
    rng = random.Random(seed)
    atlas = create_atlas_from_osm()
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())

    # 目的地：连通的 20 个 outdoor_area（在 sample_population 前算出供 home 用）
    destinations = _pick_connected_destinations(atlas, 20, rng)

    # ---- variant 解析 ----
    target_location = destinations[0] if destinations else None
    variant, controller = _build_variant_and_controller(
        variant_name, phase_days, target_location=target_location,
    )

    # 采样 agent 人群（复用 smoke demo 的 size 注入手法）
    profile_template = LANE_COVE_PROFILE.model_copy(update={
        "name": "multi-day",
        "size": n_agents,
    })
    profiles = sample_population(
        profile_template,
        seed=seed,
        home_locations=tuple(destinations),
    )

    # D catalyst_seeding 需要在构造 runtime 前改 personality
    adapter: VariantRunnerAdapter | None = None
    if variant is not None and controller is not None:
        adapter = VariantRunnerAdapter(variant, controller, seed=seed)
        profiles = adapter.setup_run(profiles, random.Random(seed + 13))

    # 每个 agent 初始化 Ledger entity + runtime + scripted plan
    runtimes: list[AgentRuntime] = []
    for p in profiles:
        home_loc = p.home_location or (rng.choice(destinations) if destinations else "unknown")
        ledger.set_entity(EntityState(
            entity_id=p.agent_id,
            position=Coord(x=0.0, y=0.0),
            location_id=home_loc,
        ))
        runtime = AgentRuntime(profile=p, current_location=home_loc)
        runtime.plan = build_scripted_plan(
            p, destinations, start_date.isoformat(), rng,
        )
        runtimes.append(runtime)

    # attention service 用于 push / shared_anchor variant；无 variant 也无成本
    attention_service = AttentionService(ledger=ledger, seed=seed)

    orchestrator = Orchestrator(
        atlas, ledger, runtimes,
        attention_service=attention_service,
        tick_minutes=5, seed=seed,
    )

    runner = MultiDayRunner(
        orchestrator=orchestrator,
        seed=seed,
        mode=mode,  # type: ignore[arg-type]
    )

    if adapter is not None:
        adapter.attach_to(runner)

    # 每日 on_day_start 重置 scripted plan + 调 variant（if any）
    def _on_day_start(current_date: date, day_index: int) -> None:
        # 1. scripted plan reset + 位置重置
        local_rng = random.Random(seed + day_index)
        for rt in runtimes:
            rt.plan = build_scripted_plan(
                rt.profile, destinations, current_date.isoformat(), local_rng,
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
        # 2. variant hook（包含 phase 判断）
        if adapter is not None:
            adapter.on_day_start(current_date, day_index)

    result = runner.run_multi_day(
        start_date=start_date,
        num_days=num_days,
        on_day_start=_on_day_start,
    )

    if adapter is not None:
        adapter.augment_result_metadata(result)

    return result


def main() -> int:
    args = parse_args()
    start_date = date.fromisoformat(args.start_date)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_dir / f"{timestamp}_{args.variant}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[run] variant={args.variant} mode={args.mode} "
          f"agents={args.agents} seeds={args.seeds} days={args.num_days}")
    print(f"[run] output → {out_dir}")

    t0 = time.perf_counter()
    per_seed_results: list[MultiDayResult] = []

    for i in range(args.seeds):
        seed = 42 + i  # deterministic seed pool
        ts = time.perf_counter()
        result = build_single_seed_run(
            seed=seed,
            n_agents=args.agents,
            start_date=start_date,
            num_days=args.num_days,
            mode=args.mode,
            variant_name=args.variant,
            phase_days=args.phase_days,
        )
        te = time.perf_counter()
        per_seed_results.append(result)

        # dump per-seed JSON
        seed_path = out_dir / f"seed_{seed}.json"
        with open(seed_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)
        print(f"  seed={seed} wall={te-ts:.1f}s ticks={result.total_ticks} "
              f"encs={result.total_encounters} → {seed_path.name}")

    # aggregate
    aggregate = MultiDayResult.combine(per_seed_results)
    agg_path = out_dir / "aggregate.json"
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(aggregate.model_dump(), f, ensure_ascii=False, indent=2)

    total_wall = time.perf_counter() - t0
    print(f"[done] wall={total_wall:.1f}s  aggregate → {agg_path}")
    print(f"       median encounters/day (day 0): "
          f"{aggregate.per_day_encounter_stats[0]['median']:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
