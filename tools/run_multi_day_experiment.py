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
from synthetic_socio_wind_tunnel.orchestrator import (
    MultiDayResult,
    MultiDayRunner,
    Orchestrator,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start-date", type=str, default="2026-04-22",
                   help="ISO format YYYY-MM-DD")
    p.add_argument("--num-days", type=int, default=14)
    p.add_argument("--agents", type=int, default=100)
    p.add_argument("--seeds", type=int, default=30,
                   help="Number of seeds to run; each seed is an independent run")
    p.add_argument("--variant", type=str, default="baseline",
                   help="Variant name (pass-through, see policy-hack change)")
    p.add_argument("--mode", choices=["dev", "publishable"], default="publishable")
    p.add_argument("--output-dir", type=Path, default=Path("data/runs"),
                   help="Base dir; per-run timestamp subdir will be created")
    return p.parse_args()


def build_single_seed_run(
    *,
    seed: int,
    n_agents: int,
    start_date: date,
    num_days: int,
    mode: str,
) -> MultiDayResult:
    """为单个 seed 搭出最小 orchestrator 栈并跑多日。"""
    rng = random.Random(seed)
    atlas = create_atlas_from_osm()
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())

    # 目的地：连通的 20 个 outdoor_area（在 sample_population 前算出供 home 用）
    destinations = _pick_connected_destinations(atlas, 20, rng)

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

    orchestrator = Orchestrator(
        atlas, ledger, runtimes,
        tick_minutes=5, seed=seed,
    )

    runner = MultiDayRunner(
        orchestrator=orchestrator,
        seed=seed,
        mode=mode,  # type: ignore[arg-type]
    )

    # 每日 on_day_start 重置 scripted plan（不消耗 LLM）
    def _on_day_start(current_date: date, day_index: int) -> None:
        local_rng = random.Random(seed + day_index)
        for rt in runtimes:
            rt.plan = build_scripted_plan(
                rt.profile, destinations, current_date.isoformat(), local_rng,
            )
            # 同时重置 Ledger 中 entity 位置回家，模拟"新的一天"
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

    return runner.run_multi_day(
        start_date=start_date,
        num_days=num_days,
        on_day_start=_on_day_start,
    )


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
