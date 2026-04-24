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
from datetime import date, datetime
from pathlib import Path

# Reuse smoke_experiment_demo helpers
sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_experiment_demo import (  # type: ignore
    build_scripted_plan,
    _pick_connected_destinations,
)

from synthetic_socio_wind_tunnel.agent import (
    AgentRuntime,
    LANE_COVE_PROFILE,
    sample_population,
)
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
    p.add_argument("--mode", choices=["dev", "publishable"], default="publishable")
    p.add_argument("--phase-days", type=str, default="4,6,4")
    p.add_argument("--start-date", type=str, default="2026-04-22")
    p.add_argument("--output-dir", type=Path, default=Path("data/experiments"))
    p.add_argument("--suite-name", type=str, default="rival_hypothesis_suite")
    return p.parse_args()


def _build_variant(
    variant_name: str,
    phase_days: str,
    *,
    target_location: str | None,
) -> tuple[Variant | None, PhaseController]:
    """解析 phase + 可选 variant 实例化。baseline 返 (None, controller)。"""
    parts = [int(x.strip()) for x in phase_days.split(",")]
    if len(parts) != 3:
        raise ValueError(f"--phase-days expects '4,6,4'; got {phase_days!r}")
    controller = PhaseController(
        baseline_days=parts[0],
        intervention_days=parts[1],
        post_days=parts[2],
    )
    if variant_name == "baseline":
        return None, controller
    cls = VARIANTS[variant_name]
    kwargs: dict = {}
    if variant_name == "hyperlocal_push" and target_location is not None:
        kwargs["target_location"] = target_location
    variant = cls(**kwargs) if kwargs else cls()
    return variant, controller


def run_seed_with_metrics(
    *,
    seed: int,
    n_agents: int,
    start_date: date,
    num_days: int,
    mode: str,
    variant_name: str,
    phase_days: str,
) -> tuple[MultiDayResult, RunMetrics, dict]:
    """单个 seed 的 metrics-enabled run；返回 (result, run_metrics, variant_metadata)."""
    rng = random.Random(seed)
    atlas = create_atlas_from_osm()
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())

    destinations = _pick_connected_destinations(atlas, 20, rng)
    target_location = destinations[0] if destinations else None

    variant, controller = _build_variant(
        variant_name, phase_days, target_location=target_location,
    )

    # 人群采样
    profile_template = LANE_COVE_PROFILE.model_copy(update={
        "name": "variant_suite",
        "size": n_agents,
    })
    profiles = sample_population(
        profile_template,
        seed=seed,
        home_locations=tuple(destinations),
    )

    adapter: VariantRunnerAdapter | None = None
    if variant is not None:
        adapter = VariantRunnerAdapter(variant, controller, seed=seed)
        profiles = adapter.setup_run(profiles, random.Random(seed + 13))

    # 初始化 runtime + Ledger entities + scripted plan
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

    attention_service = AttentionService(ledger=ledger, seed=seed)
    orchestrator = Orchestrator(
        atlas, ledger, runtimes,
        attention_service=attention_service,
        tick_minutes=5, seed=seed,
    )

    # 挂 metrics recorder
    recorder = TickMetricsRecorder(ledger=ledger, attention_service=attention_service)
    orchestrator.register_on_tick_end(recorder.on_tick_end)

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
        if adapter is not None:
            adapter.on_day_start(current_date, day_index)

    result = runner.run_multi_day(
        start_date=start_date, num_days=num_days,
        on_day_start=_on_day_start,
    )

    if adapter is not None:
        adapter.augment_result_metadata(result)

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
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suite_dir = args.output_dir / f"{ts}_{args.suite_name}"
    suite_dir.mkdir(parents=True, exist_ok=True)

    print(f"[suite] {args.suite_name} | variants={variants} | "
          f"seeds={args.seeds} × days={args.num_days} | mode={args.mode}")
    print(f"[suite] output → {suite_dir}")

    t0 = time.perf_counter()
    aggregates: dict[str, SuiteAggregate] = {}

    for variant_name in variants:
        variant_dir = suite_dir / f"variant_{variant_name}"
        variant_dir.mkdir(parents=True, exist_ok=True)
        runs: list[RunMetrics] = []
        print(f"\n[variant] {variant_name}")

        captured_variant_metadata: dict = {"name": variant_name}
        for i in range(args.seeds):
            seed = 42 + i
            t_s = time.perf_counter()
            result, run_metrics, captured_variant_metadata = run_seed_with_metrics(
                seed=seed, n_agents=args.agents, start_date=start_date,
                num_days=args.num_days, mode=args.mode,
                variant_name=variant_name, phase_days=args.phase_days,
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
            runs.append(run_metrics)
            print(f"  seed={seed} wall={t_e - t_s:.1f}s "
                  f"encs={result.total_encounters} → {seed_file.name}")

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
