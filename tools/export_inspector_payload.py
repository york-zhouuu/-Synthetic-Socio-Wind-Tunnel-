#!/usr/bin/env python3
"""
export_inspector_payload — 给"agent inspector"前端准备的回放数据导出器。

为将来作品集 web 上的 agent inspector 面板预先准备一份**离线 JSON
payload**。前端不接 sswt runtime；前端只读这份 JSON。脚本本身是
sswt 仓库内的离线工具，不动作品集仓库一行代码。

捕获 5 类数据：
  1. agents          — 被检视 agents 的 profile（personality / life_pattern / 19-dim）
  2. routines        — 每个 agent × 每日的完整 plan（看 ta 的"我的 routine"）
  3. push_history    — 每个 agent 收到过的 push（content + tick + delivered）
  4. replan_traces   — 每次 replan 的 full before/after plan（不只 diff）
  5. perception_dumps — 关键 tick 上的 SubjectiveView（"在哪看到什么"）

Usage:
    python3 tools/export_inspector_payload.py
    python3 tools/export_inspector_payload.py --num-days 7 --variant hyperlocal_push
    python3 tools/export_inspector_payload.py --use-real-llm --inspect 6

输出：data/exports/inspector-payload.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent))

# Auto-load <repo>/.env so --use-real-llm picks up GEMINI_API_KEY without
# requiring shell export. (DRY: same shim used by run_variant_suite.py)
from _env import load_dotenv as _load_dotenv  # noqa: E402
_load_dotenv()

from replan_trace import setup_run as _replan_setup_run  # type: ignore

from synthetic_socio_wind_tunnel.agent import AgentRuntime
from synthetic_socio_wind_tunnel.agent.intent import MoveIntent
from synthetic_socio_wind_tunnel.perception.models import ObserverContext
from synthetic_socio_wind_tunnel.perception.pipeline import PerceptionPipeline


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def _step_to_dict(step) -> dict[str, Any]:
    return {
        "time": step.time,
        "action": step.action,
        "destination": step.destination,
        "activity": step.activity,
        "duration_min": step.duration_minutes,
        "social_intent": step.social_intent,
        "reason": getattr(step, "reason", None),
    }


def _plan_snapshot(plan) -> list[dict[str, Any]]:
    if plan is None:
        return []
    return [_step_to_dict(s) for s in plan.steps]


class InspectorCapture:
    """订阅 on_tick_end + on_day_start 钩子，攒齐 inspector payload 五大块。"""

    def __init__(
        self,
        *,
        runtimes: list[AgentRuntime],
        atlas,
        ledger,
        attention_service,
        agent_filter: set[str],
        max_perception_dumps_per_agent: int = 5,
    ) -> None:
        self._runtimes_by_id = {r.profile.agent_id: r for r in runtimes}
        self._atlas = atlas
        self._ledger = ledger
        self._attention = attention_service
        self._filter = set(agent_filter)
        # PerceptionPipeline 用一个 lazy 单例，避免重复构造
        self._perception = PerceptionPipeline(
            atlas=atlas, ledger=ledger,
            include_digital_filter=True,
            attention_service=attention_service,
        )
        self._max_dumps_per_agent = max_perception_dumps_per_agent

        self.routines: dict[str, list[dict[str, Any]]] = {a: [] for a in self._filter}
        self.push_events: list[dict[str, Any]] = []
        self.replan_events: list[dict[str, Any]] = []
        self.perception_dumps: list[dict[str, Any]] = []

        self._last_plan_full: dict[str, list[dict[str, Any]]] = {}
        self._delivered_seen = 0
        self._last_day_index = -1
        self._dump_count: dict[str, int] = {a: 0 for a in self._filter}
        # 当 agent 收到 push 的下一个 tick，dump 一次 perception
        # （"被推送时 ta 看到什么"是 inspector 最直观的展示）
        self._pending_perception: set[str] = set()

    # --- on_day_start 钩子（外部 wrap）---

    def snapshot_day_start_routines(self, current_date: date, day_index: int) -> None:
        """on_day_start 之后调用：plan 已被重建，captured for that day."""
        weekday = current_date.strftime("%A")
        for aid in self._filter:
            rt = self._runtimes_by_id.get(aid)
            if rt is None or rt.plan is None:
                continue
            self.routines[aid].append({
                "date": current_date.isoformat(),
                "weekday": weekday,
                "day_index": day_index,
                "steps": _plan_snapshot(rt.plan),
            })
            self._last_plan_full[aid] = _plan_snapshot(rt.plan)

    # --- on_tick_end 钩子 ---

    def on_tick_end(self, tr) -> None:
        tick = tr.tick_index
        day = tr.day_index
        sim_time = tr.simulated_time.strftime("%H:%M") if tr.simulated_time else ""
        crossed_day = (
            self._last_day_index != -1 and day != self._last_day_index
        )
        self._last_day_index = day

        # 1. Push history
        log = self._attention.export_feed_log() if self._attention else ()
        for record in log[self._delivered_seen:]:
            if record.recipient_id not in self._filter:
                continue
            feed = self._attention.get_feed_item(record.feed_item_id)
            if feed is None:
                continue
            self.push_events.append({
                "agent_id": record.recipient_id,
                "tick": tick, "day": day, "simulated_time": sim_time,
                "feed_item_id": record.feed_item_id,
                "delivered": record.delivered,
                "suppressed_by_bias": record.suppressed_by_bias,
                "origin_hack_id": feed.origin_hack_id,
                "source": feed.source,
                "category": feed.category,
                "urgency": feed.urgency,
                "content": feed.content,
                "hyperlocal_radius": feed.hyperlocal_radius,
            })
            if record.delivered and not record.suppressed_by_bias:
                self._pending_perception.add(record.recipient_id)
        self._delivered_seen = len(log)

        # 2. Replan traces (full before/after plan)
        for aid in self._filter:
            rt = self._runtimes_by_id.get(aid)
            if rt is None or rt.plan is None:
                continue
            steps_now = _plan_snapshot(rt.plan)
            steps_prev = self._last_plan_full.get(aid)
            if (
                steps_prev is not None
                and steps_now != steps_prev
                and not crossed_day
            ):
                prev_dests = {s["destination"] for s in steps_prev if s["destination"]}
                now_dests = {s["destination"] for s in steps_now if s["destination"]}
                self.replan_events.append({
                    "agent_id": aid,
                    "tick": tick, "day": day, "simulated_time": sim_time,
                    "current_step_index": rt.plan.current_step_index,
                    "before_steps": steps_prev,
                    "after_steps": steps_now,
                    "added_destinations": sorted(now_dests - prev_dests),
                    "removed_destinations": sorted(prev_dests - now_dests),
                })
            self._last_plan_full[aid] = steps_now

        # 3. Perception dump on the tick AFTER a push was delivered
        for aid in list(self._pending_perception):
            if self._dump_count[aid] >= self._max_dumps_per_agent:
                self._pending_perception.discard(aid)
                continue
            rt = self._runtimes_by_id.get(aid)
            if rt is None:
                self._pending_perception.discard(aid)
                continue
            try:
                view = self._render_subjective_view(rt)
            except Exception as exc:  # pragma: no cover  (defensive)
                print(f"[warn] perception render failed for {aid}: {exc}",
                      file=sys.stderr)
                self._pending_perception.discard(aid)
                continue
            self.perception_dumps.append({
                "agent_id": aid,
                "tick": tick, "day": day, "simulated_time": sim_time,
                "trigger": "after_push",
                "location_id": view.location_id,
                "location_name": view.location_name,
                "narrative": view.narrative,
                "entities_seen": list(view.entities_seen),
                "items_noticed": list(view.items_noticed),
                "ambient_sounds": list(view.ambient_sounds),
                "ambient_smells": list(view.ambient_smells),
                "lighting": view.lighting,
                "weather": view.weather,
            })
            self._dump_count[aid] += 1
            self._pending_perception.discard(aid)

    def _render_subjective_view(self, rt: AgentRuntime):
        ctx_dict = rt.build_observer_context()
        ent = self._ledger.get_entity(rt.profile.agent_id)
        position = ent.position if ent is not None else None
        if position is None:
            from synthetic_socio_wind_tunnel.atlas.models import Coord
            position = Coord(x=0.0, y=0.0)
        ctx = ObserverContext(position=position, **ctx_dict)
        return self._perception.render(ctx)


# ---------------------------------------------------------------------------
# Agent picking
# ---------------------------------------------------------------------------


def _pick_inspector_agents(
    runtimes: list[AgentRuntime], inspect_count: int,
) -> set[str]:
    """挑一组有代表性的 agent：1 protag + 高/低 routine_adherence + 高/低 extraversion."""
    profiles = [r.profile for r in runtimes]
    by_id = {p.agent_id: p for p in profiles}

    picked: list[str] = []
    seen: set[str] = set()

    def _add(p) -> None:
        if p.agent_id not in seen:
            picked.append(p.agent_id)
            seen.add(p.agent_id)

    # 1 protagonist (优先高 extraversion 的)
    protags = [p for p in profiles if p.is_protagonist]
    if protags:
        _add(sorted(protags, key=lambda p: -p.personality.extraversion)[0])
    # 高 routine
    rest = [p for p in profiles if p.agent_id not in seen]
    if rest:
        _add(sorted(rest, key=lambda p: -p.personality.routine_adherence)[0])
    # 低 routine
    rest = [p for p in profiles if p.agent_id not in seen]
    if rest:
        _add(sorted(rest, key=lambda p: p.personality.routine_adherence)[0])
    # 高 extraversion (非 protag)
    rest = [p for p in profiles if p.agent_id not in seen and not p.is_protagonist]
    if rest:
        _add(sorted(rest, key=lambda p: -p.personality.extraversion)[0])
    # 高 curiosity
    rest = [p for p in profiles if p.agent_id not in seen]
    if rest:
        _add(sorted(rest, key=lambda p: -p.personality.curiosity)[0])
    # 余下按 id 字母序填够 inspect_count
    for p in sorted(profiles, key=lambda x: x.agent_id):
        if len(picked) >= inspect_count:
            break
        _add(p)

    return set(picked[:inspect_count])


def _profile_to_dict(profile) -> dict[str, Any]:
    """Pydantic profile → dict, with the personality / digital / life_pattern flattened."""
    out: dict[str, Any] = {
        "agent_id": profile.agent_id,
        "name": profile.name,
        "age": profile.age,
        "occupation": profile.occupation,
        "household": profile.household,
        "home_location": profile.home_location,
        "is_protagonist": profile.is_protagonist,
        "base_model": profile.base_model,
    }
    # Optional 19-dim enrichment
    for field in (
        "gender", "ethnicity", "language_at_home", "religion",
        "highest_qualification", "income_decile", "weekly_hours",
        "work_mode", "tenure_status", "vehicles_at_dwelling",
        "family_composition", "community_tenure", "unpaid_child_care_hours",
        "unpaid_assistance_hours", "volunteer_hours",
    ):
        v = getattr(profile, field, None)
        if v is not None:
            out[field] = v
    # Personality (8-dim)
    p = profile.personality
    out["personality"] = {
        "extraversion": round(p.extraversion, 3),
        "openness": round(p.openness, 3),
        "conscientiousness": round(p.conscientiousness, 3),
        "agreeableness": round(p.agreeableness, 3),
        "neuroticism": round(p.neuroticism, 3),
        "curiosity": round(p.curiosity, 3),
        "routine_adherence": round(p.routine_adherence, 3),
        "risk_tolerance": round(p.risk_tolerance, 3),
    }
    # Digital
    d = profile.digital
    out["digital"] = {
        "daily_screen_hours": round(d.daily_screen_hours, 2),
        "notification_responsiveness": round(d.notification_responsiveness, 2),
    }
    # LifePattern
    lp = profile.life_pattern
    if lp is not None:
        out["life_pattern"] = {
            "preferred_cafe": lp.preferred_cafe,
            "preferred_leisure_park": lp.preferred_leisure_park,
            "preferred_errand_destination": lp.preferred_errand_destination,
            "morning_commute_minute": lp.morning_commute_minute,
            "evening_return_minute": lp.evening_return_minute,
            "weekend_outing_destination": lp.weekend_outing_destination,
        }
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _collect_personalization(runtimes: list, inspect_ids: set) -> dict[str, Any]:
    """Per-inspected-agent audience tag (push-content-individualization).

    Provides the inspector UI a quick "what audience cluster does this agent
    belong to" answer.
    """
    from synthetic_socio_wind_tunnel.policy_hack import PushPersonalizer

    by_agent: dict[str, str] = {}
    for rt in runtimes:
        if rt.profile.agent_id in inspect_ids:
            by_agent[rt.profile.agent_id] = PushPersonalizer.audience_tag_for(
                rt.profile,
            )
    return {
        "audience_tag_by_inspected_agent": by_agent,
    }


def _collect_conversation(orchestrator, inspect_ids: set) -> dict[str, Any]:
    """Dump conversation state if any of the registered hooks attached one.

    The orchestrator hook chain wires MemoryService.process_tick which holds
    a reference to a ConversationService. We pull it via the memory service
    if discoverable; otherwise we walk recorder hooks.
    """
    # The conversation service is held by MemoryService and TickMetricsRecorder;
    # walk the orchestrator's hook callbacks to find an owner with `.conversation`.
    conv = None
    hooks_dict = getattr(orchestrator, "_hooks", {}) or {}
    for cb in hooks_dict.get("on_tick_end", []) or []:
        owner = getattr(cb, "__self__", None)
        if owner is not None and hasattr(owner, "conversation"):
            attr = owner.conversation
            if attr is not None:
                conv = attr
                break
        # MemoryService binds `process_tick` via a closure (not a method),
        # so we also peek at closure cellvars for ConversationService instance
        if conv is None:
            cells = getattr(getattr(cb, "__closure__", None) or (), "__iter__", lambda: iter([]))
            for cell in (cb.__closure__ or ()):
                inner = cell.cell_contents
                if hasattr(inner, "_conversation") and inner._conversation is not None:
                    conv = inner._conversation
                    break
            if conv is not None:
                break
    if conv is None:
        return {"available": False}

    def _info_dict(info, my_id, hops, learned_at) -> dict[str, Any]:
        return {
            "info_id": info.info_id,
            "content": info.content,
            "category": info.category,
            "salience": info.salience,
            "origin_agent_id": info.origin_agent_id,
            "origin_day_index": info.origin_day_index,
            "hops_at_learn": hops,
            "first_learned_tick": learned_at,
        }

    per_agent_known: dict[str, list[dict[str, Any]]] = {}
    for aid in sorted(inspect_ids):
        items: list[dict[str, Any]] = []
        for info_id in conv.info_known_by(aid):
            prop = conv.get_propagation(info_id)
            if prop is None:
                continue
            info = conv._infos[info_id]  # internal lookup
            items.append(_info_dict(
                info, aid, prop.hops_at[aid], prop.known_at[aid],
            ))
        items.sort(key=lambda x: (x["origin_day_index"], x["info_id"]))
        per_agent_known[aid] = items

    top = conv.top_propagated(n=5)
    top_dict = [
        {
            "info_id": p.info_id,
            "reach": p.reach,
            "max_hops": p.max_hops,
            "mean_hops": round(p.mean_hops, 3),
        }
        for p in top
    ]

    return {
        "available": True,
        "totals": {
            "info_count": conv.info_count(),
            "max_hops": conv.max_hops(),
            "info_reaching_2plus_hops": conv.count_reaching(min_hops=2),
            "avg_reach_per_info": round(conv.avg_reach(), 3),
        },
        "top_propagated": top_dict,
        "per_inspected_agent_known": per_agent_known,
    }


def _collect_social_graph(runtimes: list, inspect_ids: set) -> dict[str, Any]:
    """Dump per-inspected-agent ties + global counts.

    `runtimes` 中每个 rt 应该已挂 social_graph（由 setup_run 注入）。取一个
    存在的 graph 引用即可（所有 rt 共享同一实例）。
    """
    graph = next((rt.social_graph for rt in runtimes if rt.social_graph is not None), None)
    if graph is None:
        return {"available": False}

    def _tie_dict(t, my_id: str) -> dict[str, Any]:
        other = t.agent_b if t.agent_a == my_id else t.agent_a
        return {
            "other_agent_id": other,
            "encounter_count": t.encounter_count,
            "strength": round(t.strength, 4),
            "first_seen_tick": t.first_seen_tick,
            "last_seen_tick": t.last_seen_tick,
            "first_seen_day": t.first_seen_day,
        }

    per_agent_ties: dict[str, list[dict[str, Any]]] = {}
    for aid in sorted(inspect_ids):
        ties = graph.ties_for(aid)
        ties.sort(key=lambda t: t.strength, reverse=True)
        per_agent_ties[aid] = [_tie_dict(t, aid) for t in ties]

    return {
        "available": True,
        "K": graph.K,
        "weak_threshold": 0.1,
        "strong_threshold": 0.5,
        "totals": {
            "ties": graph.total_count(),
            "weak": graph.weak_count(),
            "strong": graph.strong_count(),
        },
        "per_inspected_agent": per_agent_ties,
    }


def _collect_replan_decision_log(runtimes: list) -> list[dict[str, Any]]:
    """收集所有 inspected runtime 的 replan_decision_log 并扁平化。"""
    out: list[dict[str, Any]] = []
    for rt in runtimes:
        for record in rt.replan_decision_log:
            out.append({
                "agent_id": record.agent_id,
                "tick": record.tick,
                "simulated_time": (
                    record.simulated_time.isoformat()
                    if record.simulated_time else None
                ),
                "candidate_kind": record.candidate_kind,
                "candidate_urgency": record.candidate_urgency,
                "threshold_computed": record.threshold_computed,
                "base_components": dict(record.base_components),
                "context_modifier": record.context_modifier,
                "replan_count_today": record.replan_count_today,
                "rng_roll": record.rng_roll,
                "decision": record.decision,
            })
    out.sort(key=lambda x: (x["agent_id"], x["tick"]))
    return out


def _git_sha(repo_root: Path) -> str:
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--variant", default="hyperlocal_push",
                   help="default: hyperlocal_push (best for showing push→replan)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--agents", type=int, default=20,
                   help="total sim population")
    p.add_argument("--inspect", type=int, default=4,
                   help="number of agents to capture in detail")
    p.add_argument("--num-days", type=int, default=7)
    p.add_argument("--phase-days", default="2,3,2")
    p.add_argument("--start-date", default="2026-04-22")
    p.add_argument("--use-real-llm", action="store_true")
    p.add_argument("--llm-provider",
                   choices=["auto", "gemini", "anthropic", "stub"],
                   default="auto")
    p.add_argument("--gemini-model", default="gemini-3-flash-preview")
    p.add_argument("--max-perception-dumps", type=int, default=5,
                   help="cap perception dumps per agent (default 5)")
    p.add_argument(
        "--output", type=Path,
        default=Path("data/exports/inspector-payload.json"),
        help="output path (default: data/exports/inspector-payload.json)",
    )
    args = p.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_path = args.output
    if not output_path.is_absolute():
        output_path = repo_root / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[setup] variant={args.variant} agents={args.agents} "
          f"inspect={args.inspect} days={args.num_days}", file=sys.stderr)

    # 1. 复用 replan_trace.setup_run 把 orchestrator 栈搭起来
    #    它内部会建 attention_service / memory / planner / runner，并接好钩子。
    #    我们传一个空的 agent_filter（先跑 setup，拿到 runtimes，再自己挑）。
    t0 = time.perf_counter()
    tracer, runner, setup, runtimes = _replan_setup_run(
        seed=args.seed, n_agents=args.agents,
        start_date=date.fromisoformat(args.start_date),
        num_days=args.num_days, variant_name=args.variant,
        phase_days=args.phase_days, use_real_llm=args.use_real_llm,
        agent_filter=None,  # default: first 5 alphabetical (we'll override)
        llm_provider=args.llm_provider,
        gemini_model=args.gemini_model,
    )

    # 2a. replan_trace.setup_run 默认 mode="dev"（限 3 天）；inspector
    #     场景需要 7 天来覆盖 weekday + weekend，这里把 runner 切成
    #     publishable mode（无天数上限）
    if args.num_days > 3:
        runner._mode = "publishable"

    # 2b. 挑选 inspect 对象（覆盖 replan_trace 的默认 filter）
    inspect_ids = _pick_inspector_agents(runtimes, args.inspect)

    # 2c. realism-attention-rebalance：被 inspect 的 agent 打开 replan
    #     decision log，suite 跑动期间记录每次 should_replan 入参 + 阈值，
    #     写入 payload 的 replan_decision_log 顶层 key
    for rt in runtimes:
        if rt.profile.agent_id in inspect_ids:
            rt.enable_replan_log = True

    # 2d. push-content-individualization：让 inspector 用的 conversation
    #     service 也接 relevance + audience providers（replan_trace.setup_run
    #     已经在内部装配，无需重复挂；但导出端要查 audience_tag 用 personalizer）
    print(f"[setup] inspecting {len(inspect_ids)} agents: "
          f"{sorted(inspect_ids)}", file=sys.stderr)

    # 3. 自己挂一套 InspectorCapture（与 ReplanTracer 并行；不冲突）
    orch = runner._orchestrator
    capture = InspectorCapture(
        runtimes=runtimes,
        atlas=orch._atlas,
        ledger=orch._ledger,
        attention_service=orch._attention_service,
        agent_filter=inspect_ids,
        max_perception_dumps_per_agent=args.max_perception_dumps,
    )
    orch.register_on_tick_end(capture.on_tick_end)

    # 4. 包一层 on_day_start：先调原 setup 的 reset 逻辑，再让 capture 拍快照
    original_on_day_start = setup["on_day_start"]

    def _on_day_start_with_capture(current_date: date, day_index: int) -> None:
        original_on_day_start(current_date, day_index)
        capture.snapshot_day_start_routines(current_date, day_index)

    # 5. 跑 sim
    print("[run] starting...", file=sys.stderr)
    runner.run_multi_day(
        start_date=setup["start_date"],
        num_days=setup["num_days"],
        on_day_start=_on_day_start_with_capture,
    )
    elapsed = time.perf_counter() - t0
    print(f"[done] wall={elapsed:.1f}s", file=sys.stderr)

    # 6. 组装 payload
    inspected_runtimes = [r for r in runtimes if r.profile.agent_id in inspect_ids]
    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": _git_sha(repo_root),
        "scope": {
            "variant": args.variant,
            "seed": args.seed,
            "n_agents_total": args.agents,
            "n_agents_inspected": len(inspect_ids),
            "num_days": args.num_days,
            "start_date": args.start_date,
            "phase_config": setup["phase_config"],
            "target_location": setup.get("target_location"),
            "shared_location": setup.get("shared_location"),
        },
        "agents": [
            _profile_to_dict(r.profile)
            for r in sorted(inspected_runtimes, key=lambda r: r.profile.agent_id)
        ],
        "routines": [
            {"agent_id": aid, "days": capture.routines[aid]}
            for aid in sorted(capture.routines)
        ],
        "push_history": sorted(
            capture.push_events,
            key=lambda e: (e["agent_id"], e["tick"]),
        ),
        "replan_traces": sorted(
            capture.replan_events,
            key=lambda e: (e["agent_id"], e["tick"]),
        ),
        "perception_dumps": sorted(
            capture.perception_dumps,
            key=lambda e: (e["agent_id"], e["tick"]),
        ),
        "replan_decision_log": _collect_replan_decision_log(inspected_runtimes),
        "social_graph": _collect_social_graph(inspected_runtimes, inspect_ids),
        "conversation": _collect_conversation(orch, inspect_ids),
        "personalization": _collect_personalization(inspected_runtimes, inspect_ids),
    }

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"[saved] {output_path}\n"
        f"  agents={len(payload['agents'])} "
        f"routines={sum(len(r['days']) for r in payload['routines'])} day-snapshots "
        f"push_history={len(payload['push_history'])} "
        f"replan_traces={len(payload['replan_traces'])} "
        f"perception_dumps={len(payload['perception_dumps'])} "
        f"replan_decisions={len(payload['replan_decision_log'])} "
        f"social_graph_ties={payload['social_graph'].get('totals', {}).get('ties', 0)} "
        f"conversation_infos={payload['conversation'].get('totals', {}).get('info_count', 0)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
