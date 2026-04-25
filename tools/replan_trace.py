#!/usr/bin/env python3
"""
replan_trace — 把 variant → memory → replan → plan change → movement 的
因果链 tick 级展开为可读 trace

跑一个小规模 sim（默认 20 agent × 3 day × 1 seed × phase 1,1,1），用
ReplanTracer 订阅 on_tick_end，捕获四类事件：
  1. feed_delivered  — variant 推送进 agent 的 attention channel
  2. plan_changed    — agent.plan 在 tick X 被替换（replan 生效信号）
  3. moved           — agent 真的从 location A → B（行为最终落地）
  4. cross-agent     — 同 tick 多 agent 收到同一 feed_item（shared_anchor 必看）

filtered 到指定 agents（默认前 5 个 alphabetical），输出可读文本或 JSON。

Usage:
    python3 tools/replan_trace.py --variant hyperlocal_push
    python3 tools/replan_trace.py --variant baseline --num-days 3
    python3 tools/replan_trace.py --variant shared_anchor --filter-agents a_42_0001,a_42_0002
    python3 tools/replan_trace.py --variant hyperlocal_push --format json --output trace.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Reuse helpers from sibling tools
sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_experiment_demo import (  # type: ignore
    build_scripted_plan,
    _pick_connected_destinations,
)
from suite_stub_llm import _pick_community_location, make_llm_client  # type: ignore

from synthetic_socio_wind_tunnel.agent import (
    AgentRuntime,
    LANE_COVE_PROFILE,
    Planner,
    sample_population,
)
from synthetic_socio_wind_tunnel.agent.intent import MoveIntent
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.attention import AttentionService
from synthetic_socio_wind_tunnel.cartography.lanecove import create_atlas_from_osm
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.memory import MemoryService
from synthetic_socio_wind_tunnel.orchestrator import (
    MultiDayRunner,
    Orchestrator,
)
from synthetic_socio_wind_tunnel.policy_hack import (
    VARIANTS,
    PhaseController,
    VariantRunnerAdapter,
)


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class ReplanTracer:
    """订阅 on_tick_end，捕获 4 类因果链事件。"""

    def __init__(
        self,
        runtimes,
        attention_service,
        *,
        agent_filter: set[str] | None = None,
    ) -> None:
        self._runtimes_by_id = {r.profile.agent_id: r for r in runtimes}
        self._attention = attention_service
        self._filter = agent_filter or set(self._runtimes_by_id.keys())
        self._events: list[dict[str, Any]] = []
        self._last_plan_steps: dict[str, list] = {}
        self._last_locations: dict[str, str | None] = {}
        self._delivered_seen: int = 0
        self._last_day_index: int = -1  # 用于检测跨日 boundary，避免把
                                         # on_day_start 的 scripted plan
                                         # 重置误报为 plan_changed

    @property
    def events(self) -> list[dict[str, Any]]:
        return self._events

    def on_tick_end(self, tr) -> None:
        tick = tr.tick_index
        day = tr.day_index
        sim_time = tr.simulated_time.strftime("%H:%M")
        # Day boundary：on_day_start 的 scripted plan reset 会让 steps 整体
        # 变化；不算 replan。我们 refresh snapshot 但跳过本 tick 的 diff。
        crossed_day_boundary = (
            self._last_day_index != -1 and day != self._last_day_index
        )
        self._last_day_index = day

        # 1. New attention deliveries since last call
        log = self._attention.export_feed_log() if self._attention else ()
        for record in log[self._delivered_seen:]:
            if record.recipient_id not in self._filter:
                continue
            feed = self._attention.get_feed_item(record.feed_item_id)
            if feed is None:
                continue
            self._events.append({
                "kind": "feed_delivered",
                "tick": tick, "day": day, "time": sim_time,
                "agent": record.recipient_id,
                "delivered": record.delivered,
                "suppressed_by_bias": record.suppressed_by_bias,
                "feed_item_id": record.feed_item_id,
                "origin_hack_id": feed.origin_hack_id,
                "source": feed.source,
                "category": feed.category,
                "urgency": feed.urgency,
                "content": feed.content[:100],
                "hyperlocal_radius": feed.hyperlocal_radius,
            })
        self._delivered_seen = len(log)

        # 2. Plan changes（跨日 boundary 时的 scripted reset 不算）
        for aid in self._filter:
            rt = self._runtimes_by_id.get(aid)
            if rt is None or rt.plan is None:
                continue
            steps_now = [
                (s.time, s.action, s.destination, s.activity[:30] if s.activity else "")
                for s in rt.plan.steps
            ]
            steps_prev = self._last_plan_steps.get(aid)
            if (steps_prev is not None and steps_now != steps_prev
                    and not crossed_day_boundary):
                # Diff: which destinations are new
                prev_dests = {s[2] for s in steps_prev if s[2]}
                now_dests = {s[2] for s in steps_now if s[2]}
                added = list(now_dests - prev_dests)
                removed = list(prev_dests - now_dests)
                self._events.append({
                    "kind": "plan_changed",
                    "tick": tick, "day": day, "time": sim_time,
                    "agent": aid,
                    "step_count_before": len(steps_prev),
                    "step_count_after": len(steps_now),
                    "added_destinations": added[:5],
                    "removed_destinations": removed[:5],
                    "current_step_index": rt.plan.current_step_index,
                })
            self._last_plan_steps[aid] = steps_now

        # 3. Successful MoveIntent commits
        for commit in tr.commits:
            if commit.agent_id not in self._filter:
                continue
            if not commit.result.success:
                continue
            if not isinstance(commit.intent, MoveIntent):
                continue
            to_loc = commit.intent.to_location
            prev = self._last_locations.get(commit.agent_id)
            if prev != to_loc:
                self._events.append({
                    "kind": "moved",
                    "tick": tick, "day": day, "time": sim_time,
                    "agent": commit.agent_id,
                    "from": prev,
                    "to": to_loc,
                })
                self._last_locations[commit.agent_id] = to_loc


# ---------------------------------------------------------------------------
# Run setup (subset of run_variant_suite.run_seed_with_metrics)
# ---------------------------------------------------------------------------

def setup_run(
    *,
    seed: int,
    n_agents: int,
    start_date: date,
    num_days: int,
    variant_name: str,
    phase_days: str,
    use_real_llm: bool,
    agent_filter: set[str] | None,
    llm_provider: str = "auto",
    gemini_model: str = "gemini-3-flash-preview",
    enable_thinking: bool = False,
) -> tuple[ReplanTracer, MultiDayRunner, dict, list[AgentRuntime]]:
    """构造完整 orchestrator 栈 + ReplanTracer，返回供 caller 跑。"""
    rng = random.Random(seed)
    atlas = create_atlas_from_osm()
    ledger = Ledger()
    ledger.current_time = datetime.combine(start_date, datetime.min.time())

    destinations = _pick_connected_destinations(atlas, 20, rng)
    target_location = destinations[0] if destinations else None

    # Variant + controller
    parts = [int(x.strip()) for x in phase_days.split(",")]
    controller = PhaseController(
        baseline_days=parts[0], intervention_days=parts[1], post_days=parts[2],
    )
    variant = None
    if variant_name != "baseline":
        cls = VARIANTS[variant_name]
        kwargs: dict = {}
        if variant_name == "hyperlocal_push" and target_location:
            kwargs["target_location"] = target_location
        variant = cls(**kwargs) if kwargs else cls()

    profile_template = LANE_COVE_PROFILE.model_copy(update={
        "name": "trace", "size": n_agents,
    })
    profiles = sample_population(
        profile_template, seed=seed,
        home_locations=tuple(destinations),
    )

    adapter: VariantRunnerAdapter | None = None
    if variant is not None:
        adapter = VariantRunnerAdapter(variant, controller, seed=seed)
        profiles = adapter.setup_run(profiles, random.Random(seed + 13))

    # Resolve agent_filter (must match actual agent_ids)
    actual_ids = {p.agent_id for p in profiles}
    if agent_filter:
        agent_filter = agent_filter & actual_ids
        if not agent_filter:
            print(
                "[warn] none of --filter-agents match actual agent_ids; "
                "falling back to first 5 alphabetical",
                file=sys.stderr,
            )
            agent_filter = set(sorted(actual_ids)[:5])
    else:
        agent_filter = set(sorted(actual_ids)[:5])

    runtimes: list[AgentRuntime] = []
    for p in profiles:
        home_loc = p.home_location or (
            rng.choice(destinations) if destinations else "unknown"
        )
        ledger.set_entity(EntityState(
            entity_id=p.agent_id, position=Coord(x=0.0, y=0.0),
            location_id=home_loc,
        ))
        rt = AgentRuntime(profile=p, current_location=home_loc)
        rt.plan = build_scripted_plan(
            p, destinations, start_date.isoformat(), rng,
        )
        runtimes.append(rt)

    attention_service = AttentionService(ledger=ledger, seed=seed)
    orchestrator = Orchestrator(
        atlas, ledger, runtimes, attention_service=attention_service,
        tick_minutes=5, seed=seed,
    )

    # ---- Tracer ----
    tracer = ReplanTracer(
        runtimes, attention_service, agent_filter=agent_filter,
    )
    orchestrator.register_on_tick_end(tracer.on_tick_end)

    # Memory + Planner（与 suite-wiring 同步装配）
    shared_loc = _pick_community_location(atlas, tuple(destinations))
    llm_client = make_llm_client(
        use_real=use_real_llm, variant_name=variant_name, seed=seed,
        target_location=target_location, shared_location=shared_loc,
        provider=llm_provider, gemini_model=gemini_model,
        enable_thinking=enable_thinking,
    )
    planner = Planner(llm_client=llm_client)
    memory = MemoryService(attention_service=attention_service)
    agents_by_id = {r.profile.agent_id: r for r in runtimes}

    def _memory_hook(tr) -> None:
        memory.process_tick(tr, agents_by_id, planner)

    orchestrator.register_on_tick_end(_memory_hook)

    runner = MultiDayRunner(
        orchestrator=orchestrator, seed=seed, mode="dev",
    )
    if adapter is not None:
        adapter.attach_to(runner)

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

    setup = {
        "start_date": start_date,
        "num_days": num_days,
        "on_day_start": _on_day_start,
        "agent_filter": agent_filter,
        "target_location": target_location,
        "shared_location": shared_loc,
        "phase_config": controller.model_dump(),
    }
    return tracer, runner, setup, runtimes


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

_KIND_GLYPH = {
    "feed_delivered": "📨",
    "plan_changed":   "📝",
    "moved":          "🚶",
}


def render_text(
    events: list[dict[str, Any]],
    *,
    setup_info: dict[str, Any],
    max_events: int | None = None,
) -> str:
    out: list[str] = []
    out.append("═" * 75)
    out.append(f"REPLAN TRACE — variant={setup_info['variant_name']} "
               f"seed={setup_info['seed']} agents={setup_info['n_agents']}")
    out.append(f"  num_days={setup_info['num_days']} "
               f"phase={setup_info['phase_config']}")
    if setup_info.get("target_location"):
        out.append(f"  target_location: {setup_info['target_location']}")
    out.append(f"  filter_agents: {sorted(setup_info['agent_filter'])}")
    out.append(f"  total events captured: {len(events)}")
    out.append("═" * 75)

    capped = events[:max_events] if max_events else events

    # Group by (day, agent) for readability
    from itertools import groupby
    capped_sorted = sorted(
        capped,
        key=lambda e: (e["day"], e["agent"], e["tick"]),
    )

    last_key: tuple | None = None
    for ev in capped_sorted:
        key = (ev["day"], ev["agent"])
        if key != last_key:
            day = ev["day"]
            phase = _phase_for(day, setup_info["phase_config"])
            out.append("")
            out.append(f"┌─ Day {day} ({phase}) — agent {ev['agent']}")
            last_key = key

        glyph = _KIND_GLYPH.get(ev["kind"], "•")
        line = f"│ tick {ev['tick']:>3} {ev['time']} {glyph} {ev['kind']:<14}"

        if ev["kind"] == "feed_delivered":
            tag = "✓" if ev["delivered"] else "✗ (suppressed)"
            line += (
                f" {tag} | hack={ev['origin_hack_id']!s:<22}"
                f" urg={ev['urgency']:.1f}"
            )
            out.append(line)
            out.append(f"│            └── {ev['content']!r}")
        elif ev["kind"] == "plan_changed":
            line += (
                f" | steps {ev['step_count_before']}→{ev['step_count_after']}"
            )
            out.append(line)
            if ev["added_destinations"]:
                out.append(f"│            └── + dest: {ev['added_destinations']}")
            if ev["removed_destinations"]:
                out.append(f"│            └── − dest: {ev['removed_destinations']}")
        elif ev["kind"] == "moved":
            line += f" | {ev['from']} → {ev['to']}"
            out.append(line)
        else:
            out.append(line + f" | {ev}")

    if max_events and len(events) > max_events:
        out.append("")
        out.append(f"... (truncated; {len(events) - max_events} more events; "
                   f"use --max-events to see more)")

    out.append("")
    out.append("═" * 75)
    out.append("Summary by kind:")
    counts: dict[str, int] = {}
    for ev in events:
        counts[ev["kind"]] = counts.get(ev["kind"], 0) + 1
    for k, n in sorted(counts.items()):
        out.append(f"  {_KIND_GLYPH.get(k, '•')} {k:<16} {n}")
    out.append("═" * 75)

    return "\n".join(out)


def _phase_for(day: int, phase_cfg: dict) -> str:
    b = phase_cfg["baseline_days"]
    i = phase_cfg["intervention_days"]
    if day < b:
        return "baseline"
    if day < b + i:
        return "intervention"
    return "post"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_KNOWN_VARIANTS = ["baseline"] + sorted(VARIANTS.keys())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--variant", required=True, choices=_KNOWN_VARIANTS)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--agents", type=int, default=20)
    p.add_argument("--num-days", type=int, default=3)
    p.add_argument("--phase-days", default="1,1,1")
    p.add_argument("--start-date", default="2026-04-26")
    p.add_argument("--filter-agents", default=None,
                   help="comma-separated agent_ids; default first 5 by id sort")
    p.add_argument("--use-real-llm", action="store_true")
    p.add_argument("--llm-provider", choices=["auto", "gemini", "anthropic", "stub"],
                   default="auto",
                   help="default 'auto': 优先检 GEMINI_API_KEY，其次 ANTHROPIC_API_KEY")
    p.add_argument("--gemini-model", default="gemini-3-flash-preview")
    p.add_argument("--enable-thinking", action="store_true",
                   help="Gemini 默认关 thinking；加此 flag 开启（更慢更贵）")
    p.add_argument("--max-events", type=int, default=None,
                   help="cap rendered events; full count still in summary")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()

    agent_filter = None
    if args.filter_agents:
        agent_filter = {x.strip() for x in args.filter_agents.split(",") if x.strip()}

    print(f"[setup] variant={args.variant} seed={args.seed} "
          f"agents={args.agents} days={args.num_days}", file=sys.stderr)

    t0 = time.perf_counter()
    tracer, runner, setup, _runtimes = setup_run(
        seed=args.seed, n_agents=args.agents,
        start_date=date.fromisoformat(args.start_date),
        num_days=args.num_days, variant_name=args.variant,
        phase_days=args.phase_days, use_real_llm=args.use_real_llm,
        agent_filter=agent_filter,
        llm_provider=args.llm_provider,
        gemini_model=args.gemini_model,
        enable_thinking=args.enable_thinking,
    )

    print(f"[run] starting...", file=sys.stderr)
    runner.run_multi_day(
        start_date=setup["start_date"], num_days=setup["num_days"],
        on_day_start=setup["on_day_start"],
    )
    elapsed = time.perf_counter() - t0
    print(f"[done] wall={elapsed:.1f}s captured={len(tracer.events)} events",
          file=sys.stderr)

    setup_info = {
        "variant_name": args.variant,
        "seed": args.seed,
        "n_agents": args.agents,
        "num_days": args.num_days,
        "phase_config": setup["phase_config"],
        "target_location": setup.get("target_location"),
        "shared_location": setup.get("shared_location"),
        "agent_filter": setup["agent_filter"],
    }

    if args.format == "json":
        out_data = {"setup": setup_info, "events": tracer.events}
        # Make agent_filter serialisable
        out_data["setup"]["agent_filter"] = sorted(setup_info["agent_filter"])
        text = json.dumps(out_data, ensure_ascii=False, indent=2)
    else:
        text = render_text(
            tracer.events, setup_info=setup_info,
            max_events=args.max_events,
        )

    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"[saved] {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
