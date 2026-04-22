#!/usr/bin/env python3
"""
smoke_experiment_demo — Experiment 1 (Digital Lure) 的端到端集成冒烟测试

不是单元测试。验证 orchestrator + attention + memory + typed-personality
拼装在 Lane Cove atlas 真实数据 + 100 agent × 288 tick 规模下能否跑通
并产出 thesis 层信号。

8 条子目标（A-H），每条对应具体指标 + 阈值。

Usage:
    python3 tools/smoke_experiment_demo.py
    python3 tools/smoke_experiment_demo.py --agents 50 --debug
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# ---- imports from the framework ----
from synthetic_socio_wind_tunnel.agent import (
    AgentProfile,
    AgentRuntime,
    DailyPlan,
    LANE_COVE_PROFILE,
    Planner,
    PlanStep,
    sample_population,
)
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention import AttentionService, FeedItem
from synthetic_socio_wind_tunnel.cartography.lanecove import create_atlas_from_osm
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.memory import MemoryService
from synthetic_socio_wind_tunnel.orchestrator import Orchestrator, TickResult


# ============================================================================
# Config
# ============================================================================

@dataclass
class SmokeConfig:
    n_agents: int = 100
    n_destinations: int = 20  # 多少个预定目的地池
    seed: int = 42
    tick_minutes: int = 5
    # 干预时间：tick 12 = 7:00 + 12×5min = 08:00（早晨通勤时段）
    intervention_tick: int = 12
    simulation_start: datetime = datetime(2026, 4, 21, 7, 0, 0)
    # 推送参数
    push_urgency: float = 0.9
    # 门禁阈值（报告判定用）
    budget_wall_time_seconds: float = 600.0


# ============================================================================
# Rule-based plan generator — 不调 LLM
# ============================================================================

def build_scripted_plan(
    profile: AgentProfile,
    destinations: list[str],
    date: str,
    rng: random.Random,
) -> DailyPlan:
    """
    基于人格生成一个粗糙的日程：
      home → work-ish → lunch → afternoon → dinner → home
    routine_adherence 高 → 目的地更稳定；低 → 更多跳转。
    """
    adherence = profile.personality.routine_adherence
    num_slots = 4 if adherence > 0.5 else 6  # 低坚持者日程更碎

    # 时间锚点
    steps: list[PlanStep] = []
    # wake_time 从 profile 读
    wake_hour = int(profile.wake_time.split(":")[0])
    current_hour = wake_hour

    # 初始 move 到 "work-like" 目的地
    for slot_idx in range(num_slots):
        dest = rng.choice(destinations)
        duration = rng.choice([30, 60, 90, 120])  # 30-120 分钟
        steps.append(PlanStep(
            time=f"{current_hour}:{(slot_idx * 17) % 60:02d}",
            action="move",
            destination=dest,
            duration_minutes=duration,
            activity=rng.choice(["work", "coffee", "errands", "reading", "walking"]),
            social_intent=rng.choice(["alone", "open_to_chat"]),
            reason="scripted plan",
        ))
        current_hour = min(22, current_hour + max(1, duration // 60))

    return DailyPlan(
        agent_id=profile.agent_id,
        date=date,
        steps=steps,
        current_step_index=0,
    )


# ============================================================================
# Stub LLM for replan — 不花钱
# ============================================================================

class StubReplanLLM:
    """
    返回一个总是"move 到 target_location"的 plan JSON。

    关键：step 的 `time` 字段基于**当前 simulated_time + 15min**动态计算，
    否则 AgentRuntime._current_step_expired 会把"早于当前时间"的 step 立刻
    判为过期、auto-advance 跳过，agent 永远不移动。

    让我们验证 replan 的**集成**正确性，而不是 prompt 质量。
    """

    def __init__(self, target_location: str, ledger: Ledger):
        self.target_location = target_location
        self._ledger = ledger  # 读 current_time 动态计算 step 时间
        self.calls = 0

    async def generate(self, prompt: str, *, model: str = "", **kwargs) -> str:
        self.calls += 1
        # 基于当前模拟时间 + 15min 作为 move step 开始时间
        now = self._ledger.current_time
        move_start = now.replace(second=0, microsecond=0)
        move_time = f"{move_start.hour}:{(move_start.minute + 15) % 60:02d}"
        stay_hour = move_start.hour + 1
        stay_time = f"{min(23, stay_hour)}:30"
        return json.dumps([
            {
                "time": move_time,
                "action": "move",
                "destination": self.target_location,
                "duration_minutes": 60,
                "activity": "responding_to_push",
                "reason": "replan from intervention",
                "social_intent": "open_to_chat",
            },
            {
                "time": stay_time,
                "action": "stay",
                "destination": self.target_location,
                "duration_minutes": 60,
                "activity": "lingering",
                "reason": "post-push loiter",
                "social_intent": "open_to_chat",
            },
        ])


# ============================================================================
# Helpers
# ============================================================================

def _pick_connected_destinations(
    atlas: Atlas,
    n: int,
    rng: random.Random,
) -> list[str]:
    """
    BFS 从一个种子 outdoor_area 出发，找出 n 个 mutual-reachable 的
    outdoor_area。避免 agent 的 plan 指向不连通的子图。
    """
    outdoor_ids = list(atlas.region.outdoor_areas.keys())
    if not outdoor_ids:
        raise ValueError("atlas has no outdoor_areas")

    # 建邻接索引（一次构造，O(E)）
    adjacency: dict[str, set[str]] = {}
    for conn in atlas.region.connections:
        adjacency.setdefault(conn.from_id, set()).add(conn.to_id)
        if conn.bidirectional:
            adjacency.setdefault(conn.to_id, set()).add(conn.from_id)

    # 从不同种子尝试 BFS，直到找到一个 ≥ n 的连通分量
    rng.shuffle(outdoor_ids)
    for seed in outdoor_ids:
        visited: set[str] = {seed}
        queue: list[str] = [seed]
        while queue and len(visited) < n * 5:  # 容量为 n 的 5 倍 pool
            current = queue.pop(0)
            for neighbor in adjacency.get(current, ()):
                if neighbor not in visited and neighbor in atlas.region.outdoor_areas:
                    visited.add(neighbor)
                    queue.append(neighbor)
        if len(visited) >= n:
            return rng.sample(list(visited), n)

    raise ValueError(
        f"no connected component with >= {n} outdoor_areas (largest attempted)"
    )


def _polygon_center(polygon) -> Coord:
    """Polygon.vertices 是 tuple[Coord, ...]; 中心 = 顶点坐标均值。"""
    verts = polygon.vertices
    if not verts:
        return Coord(x=0.0, y=0.0)
    mx = sum(v.x for v in verts) / len(verts)
    my = sum(v.y for v in verts) / len(verts)
    return Coord(x=mx, y=my)


def _location_center(atlas: Atlas, location_id: str) -> Coord:
    loc = atlas.get_location(location_id)
    if loc is None:
        return Coord(x=0.0, y=0.0)
    return _polygon_center(loc.polygon)


def _distance(a: Coord, b: Coord) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)


# ============================================================================
# Metrics collector
# ============================================================================

@dataclass
class Metrics:
    # A
    plans_generated: int = 0
    total_plan_steps: int = 0
    # B
    move_commits_success: int = 0
    move_commits_failed: int = 0
    unique_locations_visited: set[str] = field(default_factory=set)
    # C
    total_encounters: int = 0
    encounters_per_tick: list[int] = field(default_factory=list)
    # D
    memory_events_per_agent: dict[str, int] = field(default_factory=dict)
    # E
    notifications_delivered_target: int = 0
    notifications_delivered_control: int = 0
    # F
    replans_triggered: int = 0
    replan_agent_ids: list[str] = field(default_factory=list)
    # G
    target_final_distances: list[float] = field(default_factory=list)
    control_final_distances: list[float] = field(default_factory=list)
    # H
    wall_time_seconds: float = 0.0


# ============================================================================
# Main experiment
# ============================================================================

def run_smoke(cfg: SmokeConfig, *, debug: bool = False) -> Metrics:
    rng = random.Random(cfg.seed)
    metrics = Metrics()

    # ---- Atlas ----
    print("[setup] loading Lane Cove atlas...")
    atlas = create_atlas_from_osm()
    outdoor_ids = list(atlas.region.outdoor_areas.keys())
    if len(outdoor_ids) < cfg.n_destinations:
        sys.exit(f"atlas has only {len(outdoor_ids)} outdoor areas, need >= {cfg.n_destinations}")

    # 固定一组"常去地点"——BFS 保证它们 mutual-reachable，避免 NavigationService 失败
    destinations = _pick_connected_destinations(atlas, cfg.n_destinations, rng)
    target_location = destinations[0]  # push 导向第一个
    print(f"[setup] atlas: {len(outdoor_ids)} outdoor areas, "
          f"{len(atlas.region.buildings)} buildings")
    print(f"[setup] {cfg.n_destinations} common destinations; "
          f"target = {target_location}")

    # ---- Agents ----
    profile_template = LANE_COVE_PROFILE.model_copy(update={
        "name": "smoke",
        "size": cfg.n_agents,
    })
    profiles = sample_population(
        profile_template, seed=cfg.seed,
        home_locations=tuple(destinations),  # 居住在这些 outdoor_area 中之一
    )

    # 把前一半划为 target，后一半划为 control
    sorted_profiles = sorted(profiles, key=lambda p: p.agent_id)
    half = len(sorted_profiles) // 2
    target_ids = {p.agent_id for p in sorted_profiles[:half]}
    control_ids = {p.agent_id for p in sorted_profiles[half:]}

    # ---- Plans (A) ----
    agents: list[AgentRuntime] = []
    for profile in profiles:
        plan = build_scripted_plan(
            profile, destinations, "2026-04-21",
            rng=random.Random(hash(profile.agent_id) & 0xFFFFFFFF),
        )
        metrics.plans_generated += 1
        metrics.total_plan_steps += len(plan.steps)
        runtime = AgentRuntime(
            profile=profile,
            plan=plan,
            current_location=profile.home_location,
        )
        agents.append(runtime)
    print(f"[A] plans_generated = {metrics.plans_generated}, "
          f"total_steps = {metrics.total_plan_steps}")

    # ---- Ledger ----
    ledger = Ledger()
    ledger.current_time = cfg.simulation_start
    for runtime in agents:
        home_center = _location_center(atlas, runtime.current_location)
        ledger.set_entity(EntityState(
            entity_id=runtime.profile.agent_id,
            location_id=runtime.current_location,
            position=home_center,
        ))

    # ---- Services ----
    attention = AttentionService(ledger, seed=cfg.seed)
    memory = MemoryService(attention_service=attention)
    stub_llm = StubReplanLLM(target_location=target_location, ledger=ledger)
    planner = Planner(stub_llm)

    orch = Orchestrator(
        atlas, ledger, agents,
        attention_service=attention,
        tick_minutes=cfg.tick_minutes,
        seed=cfg.seed,
    )

    # ---- Intervention hook ----
    def inject_push_at_tick(tick_ctx):
        if tick_ctx.tick_index == cfg.intervention_tick:
            item = FeedItem(
                feed_item_id=f"push_exp1_{cfg.seed}",
                content=f"限时：{target_location} 附近的 pop-up 活动 "
                        f"现在开始，30 分钟后结束",
                # commercial_push 不走 feed_bias 抑制路径；测纯集成
                # （真实 Experiment 用 local_news 才会触发算法偏向效应）
                source="commercial_push",
                hyperlocal_radius=500.0,
                urgency=cfg.push_urgency,
                category="event",
                created_at=ledger.current_time,
            )
            attention.inject_feed_item(item, sorted(target_ids))
            print(f"[intervention] tick {tick_ctx.tick_index}: pushed to "
                  f"{len(target_ids)} target agents → {target_location}")

    # ---- on_tick_end: memory.process_tick ----
    agents_by_id = {a.profile.agent_id: a for a in agents}

    def on_tick_end(tick_result: TickResult):
        replans = memory.process_tick(tick_result, agents_by_id, planner)
        metrics.total_encounters += len(tick_result.encounter_candidates)
        metrics.encounters_per_tick.append(len(tick_result.encounter_candidates))
        for commit in tick_result.commits:
            if type(commit.intent).__name__ == "MoveIntent":
                if commit.result.success:
                    metrics.move_commits_success += 1
                else:
                    metrics.move_commits_failed += 1
        for replan_agent_id, _event in replans:
            metrics.replans_triggered += 1
            metrics.replan_agent_ids.append(replan_agent_id)

    orch.register_on_tick_start(inject_push_at_tick)
    orch.register_on_tick_end(on_tick_end)

    # Per-agent trajectory trace (only for --trace-agent)
    trace_agent = getattr(cfg, "trace_agent", None)
    if trace_agent is not None and trace_agent in agents_by_id:
        print(f"\n[trace] following agent: {trace_agent}")
        print(f"[trace] original plan steps:")
        for i, s in enumerate(agents_by_id[trace_agent].plan.steps):
            print(f"   [{i}] {s.time} action={s.action} dest={s.destination} dur={s.duration_minutes}")

        def dump_tick(tick_result):
            if tick_result.tick_index in {95, 96, 97, 98, 110, 113, 127, 150, 287}:
                agent = agents_by_id[trace_agent]
                entity = ledger.get_entity(trace_agent)
                plan = agent.plan
                current = plan.current() if plan else None
                print(f"[trace tick={tick_result.tick_index} "
                      f"time={tick_result.simulated_time.strftime('%H:%M')}] "
                      f"loc={entity.location_id if entity else '?'}  "
                      f"plan_idx={plan.current_step_index if plan else '?'}/{len(plan.steps) if plan else 0}  "
                      f"current={current.action+'→'+str(current.destination) if current else None}")

        orch.register_on_tick_end(dump_tick)

    # ---- Run ----
    print(f"[run] starting orchestrator: {len(agents)} agents × "
          f"{orch._ticks_per_day} ticks = {len(agents) * orch._ticks_per_day} "
          f"agent-ticks")
    t0 = time.perf_counter()
    orch.run()
    metrics.wall_time_seconds = time.perf_counter() - t0

    # ---- Post-run metrics ----

    # B: unique locations visited (from Ledger final states + any hops
    # recorded in memory action events)
    for aid in agents_by_id:
        entity = ledger.get_entity(aid)
        if entity:
            metrics.unique_locations_visited.add(entity.location_id)
    # 从 memory 事件里也拿走过的 location
    for aid in agents_by_id:
        for ev in memory.all_for(aid):
            if ev.location_id:
                metrics.unique_locations_visited.add(ev.location_id)

    # D: events per agent
    for aid in agents_by_id:
        metrics.memory_events_per_agent[aid] = len(memory.all_for(aid))

    # E: notification delivery breakdown
    for aid in target_ids:
        notifs = [e for e in memory.all_for(aid) if e.kind == "notification"]
        if notifs:
            metrics.notifications_delivered_target += 1
    for aid in control_ids:
        notifs = [e for e in memory.all_for(aid) if e.kind == "notification"]
        if notifs:
            metrics.notifications_delivered_control += 1

    # G: final distances to target
    target_center = _location_center(atlas, target_location)
    target_details: list[tuple[str, str, float]] = []
    control_details: list[tuple[str, str, float]] = []
    for aid in target_ids:
        entity = ledger.get_entity(aid)
        if entity:
            end_center = _location_center(atlas, entity.location_id)
            d = _distance(end_center, target_center)
            metrics.target_final_distances.append(d)
            target_details.append((aid, entity.location_id, d))
    for aid in control_ids:
        entity = ledger.get_entity(aid)
        if entity:
            end_center = _location_center(atlas, entity.location_id)
            d = _distance(end_center, target_center)
            metrics.control_final_distances.append(d)
            control_details.append((aid, entity.location_id, d))

    if debug:
        print(f"\n[debug] target_location = {target_location}")
        print("[debug] sample target agents (first 10):")
        for aid, loc, d in sorted(target_details)[:10]:
            at_target = "← AT TARGET" if loc == target_location else ""
            print(f"  {aid}  final={loc}  dist={d:7.1f}m  {at_target}")
        at_target_count = sum(1 for _, loc, _ in target_details
                              if loc == target_location)
        print(f"[debug] target agents AT target_location: "
              f"{at_target_count} / {len(target_details)}")
        control_at_target = sum(1 for _, loc, _ in control_details
                                if loc == target_location)
        print(f"[debug] control agents AT target_location: "
              f"{control_at_target} / {len(control_details)}")

    return metrics


# ============================================================================
# Report
# ============================================================================

def _passfail(ok: bool) -> str:
    return "✓" if ok else "✗"


def report(cfg: SmokeConfig, m: Metrics) -> None:
    print()
    print("=" * 68)
    print(f"SMOKE EXPERIMENT REPORT  (seed={cfg.seed}, agents={cfg.n_agents})")
    print("=" * 68)

    # A
    a_ok = m.plans_generated >= cfg.n_agents and m.total_plan_steps > cfg.n_agents * 3
    print(f"[A] plan generation                                     {_passfail(a_ok)}")
    print(f"    plans_generated: {m.plans_generated}  (>= {cfg.n_agents})")
    print(f"    total_steps: {m.total_plan_steps}  (>= {cfg.n_agents * 3})")

    # B
    total_moves = m.move_commits_success + m.move_commits_failed
    b_ok = (
        m.move_commits_success >= cfg.n_agents * 5
        and len(m.unique_locations_visited) >= 10
    )
    print(f"[B] movement                                            {_passfail(b_ok)}")
    print(f"    move_success: {m.move_commits_success} / "
          f"failed: {m.move_commits_failed} / total: {total_moves}")
    print(f"    unique_locations_visited: {len(m.unique_locations_visited)}  (>= 10)")

    # C
    c_ok = m.total_encounters > 0
    print(f"[C] encounter detection                                 {_passfail(c_ok)}")
    print(f"    total_encounters: {m.total_encounters}  (> 0)")
    if m.encounters_per_tick:
        ticks_with_encounters = sum(1 for n in m.encounters_per_tick if n > 0)
        print(f"    ticks_with_encounters: {ticks_with_encounters} / "
              f"{len(m.encounters_per_tick)}")

    # D
    events_list = list(m.memory_events_per_agent.values())
    d_ok = len(events_list) == cfg.n_agents and min(events_list, default=0) > 0
    median_events = statistics.median(events_list) if events_list else 0
    print(f"[D] memory events                                       {_passfail(d_ok)}")
    print(f"    events_per_agent median: {int(median_events)}")
    if events_list:
        print(f"    min/max: {min(events_list)} / {max(events_list)}")

    # E
    # target 全部应拿到推送；control 全部应拿不到
    half = cfg.n_agents // 2
    e_ok = (
        m.notifications_delivered_target >= half * 0.9  # 允许一些被 bias 抑制
        and m.notifications_delivered_control == 0
    )
    print(f"[E] attention channel                                   {_passfail(e_ok)}")
    print(f"    notif→target: {m.notifications_delivered_target} / {half}  (>= {int(half * 0.9)})")
    print(f"    notif→control: {m.notifications_delivered_control} / {half}  (== 0)")

    # F
    f_ok = m.replans_triggered >= 1
    print(f"[F] replan trigger                                      {_passfail(f_ok)}")
    print(f"    replans_triggered: {m.replans_triggered}  (>= 1)")
    if m.replan_agent_ids:
        unique_replan = len(set(m.replan_agent_ids))
        print(f"    distinct agents: {unique_replan}")

    # G
    g_ok = False
    if m.target_final_distances and m.control_final_distances:
        target_median = statistics.median(m.target_final_distances)
        control_median = statistics.median(m.control_final_distances)
        delta = control_median - target_median
        g_ok = delta > 50.0
        print(f"[G] thesis signal (distance to push target)             {_passfail(g_ok)}")
        print(f"    target median: {target_median:.1f}m")
        print(f"    control median: {control_median:.1f}m")
        print(f"    delta: {delta:+.1f}m  (target should be closer; delta > 50m)")
    else:
        print(f"[G] thesis signal                                       ✗")
        print(f"    no distances collected")

    # H
    h_ok = m.wall_time_seconds < cfg.budget_wall_time_seconds
    mins = int(m.wall_time_seconds // 60)
    secs = m.wall_time_seconds - mins * 60
    print(f"[H] performance                                         {_passfail(h_ok)}")
    print(f"    wall time: {mins}m {secs:.1f}s  (< {cfg.budget_wall_time_seconds:.0f}s)")
    print(f"    per-tick avg: "
          f"{m.wall_time_seconds / max(1, len(m.encounters_per_tick)) * 1000:.1f} ms")

    print("=" * 68)

    # Summary
    total_checks = 8
    passed = sum([a_ok, b_ok, c_ok, d_ok, e_ok, f_ok, g_ok, h_ok])
    print(f"\nSUMMARY: {passed} / {total_checks} sub-goals PASS")
    if passed == total_checks:
        print("→ 全栈集成可用于下一步 Experiment 1 设计")
    else:
        print("→ 有子目标未达标；见上方具体指标")


# ============================================================================
# CLI
# ============================================================================

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--agents", type=int, default=100)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--intervention-tick", type=int, default=96)
    p.add_argument("--trace-agent", type=str, default=None,
                   help="print tick-by-tick trajectory for this agent_id")
    p.add_argument("--multi-day", action="store_true",
                   help="use MultiDayRunner for a 3-day dev-mode run "
                        "(basic pipeline smoke; not publishable)")
    args = p.parse_args()

    if args.multi_day:
        # Lightweight dispatch to the multi-day CLI for a smoke run.
        # Experiment variants and metrics don't live here — see
        # tools/run_multi_day_experiment.py for a richer entry.
        from datetime import date
        from synthetic_socio_wind_tunnel.orchestrator import MultiDayRunner
        print("[smoke --multi-day] 3 day × 1 seed × "
              f"{args.agents} agents dev-mode smoke ...")
        # Reuse the richer CLI for this code path.
        from run_multi_day_experiment import build_single_seed_run
        t0 = time.time()
        result = build_single_seed_run(
            seed=args.seed,
            n_agents=args.agents,
            start_date=date(2026, 4, 22),
            num_days=3,
            mode="dev",
        )
        dt = time.time() - t0
        print(f"[smoke --multi-day] wall={dt:.1f}s "
              f"ticks={result.total_ticks} encs={result.total_encounters}")
        per_day = result.per_day_summaries
        for d in per_day:
            print(f"  day {d.day_index} ({d.simulated_date}): "
                  f"ticks={d.tick_count} encs={d.encounter_count}")
        return 0

    cfg = SmokeConfig(
        n_agents=args.agents,
        seed=args.seed,
        intervention_tick=args.intervention_tick,
    )
    cfg.trace_agent = args.trace_agent  # type: ignore
    metrics = run_smoke(cfg, debug=args.debug)
    report(cfg, metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
