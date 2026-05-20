"""
Orchestrator — tick 循环主类

tick 内顺序（见 design D4）：
  1. on_tick_start
  2. 对每 agent (字典序): build observer_context → agent.step() → intent_pool
  3. IntentResolver.resolve(intent_pool) → [CommitDecision]
  4. 对每 CommitDecision: 分派到 SimulationService；MoveIntent 逐 step 写 Ledger + 记 trace
  5. 扫 trace → EncounterCandidate[]
  6. Ledger.current_time += tick_minutes
  7. on_tick_end(TickResult)
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Awaitable, Callable

from synthetic_socio_wind_tunnel.agent.intent import (
    ExamineIntent,
    Intent,
    LockIntent,
    MoveIntent,
    OpenDoorIntent,
    PickupIntent,
    UnlockIntent,
    WaitIntent,
)
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.core.errors import SimulationErrorCode
from synthetic_socio_wind_tunnel.engine.navigation import NavigationService
from synthetic_socio_wind_tunnel.engine.simulation import (
    SimulationResult,
    SimulationService,
)
from synthetic_socio_wind_tunnel.orchestrator.intent_resolver import (
    CommitDecision,
    IntentResolver,
)
from synthetic_socio_wind_tunnel.orchestrator.models import (
    CommitRecord,
    EncounterCandidate,
    HookName,
    SimulationContext,
    SimulationSummary,
    TickContext,
    TickMovementTrace,
    TickResult,
)
from synthetic_socio_wind_tunnel.perception.models import ObserverContext
from synthetic_socio_wind_tunnel.perception.pipeline import PerceptionPipeline

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.runtime import AgentRuntime
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.attention import AttentionService
    from synthetic_socio_wind_tunnel.ledger import Ledger


_HOOK_NAMES: tuple[HookName, ...] = (
    "on_simulation_start",
    "on_tick_start",
    "on_tick_end",
    "on_simulation_end",
)


class Orchestrator:
    """单天 tick 循环驱动。"""

    __slots__ = (
        "_atlas",
        "_ledger",
        "_agents",
        "_simulation",
        "_pipeline",
        "_navigation",
        "_attention_service",
        "_tick_minutes",
        "_ticks_per_day",
        "_seed",
        "_num_days",
        "_resolver",
        "_hooks",
        "_async_tick_end_hooks",
        "_walking_speed_m_per_min",
        # H3 (persistent-asyncio-loop, 2026-05-21): one loop reused
        # across all ticks instead of fresh asyncio.run() per tick.
        "_persistent_loop",
    )

    def __init__(
        self,
        atlas: "Atlas",
        ledger: "Ledger",
        agents: list["AgentRuntime"],
        *,
        simulation: SimulationService | None = None,
        pipeline: PerceptionPipeline | None = None,
        navigation: NavigationService | None = None,
        attention_service: "AttentionService | None" = None,
        tick_minutes: int = 5,
        seed: int = 0,
        num_days: int = 1,
        walking_speed_m_per_min: float = 80.0,
    ) -> None:
        # -- validate --
        # num_days=1 是单日默认；>1 由 MultiDayRunner 按天循环调 run()
        # 实现（Orchestrator 本身只负责 1 天的 288 tick 循环）。若调用方
        # 传 num_days>1 又直接调 run()，结果是"跑 N 天量的 tick 在一天
        # 的 Ledger 时间上"——非预期；给出明确指引。
        if num_days < 1:
            raise ValueError(f"num_days must be >= 1, got {num_days}")
        if num_days > 1:
            raise ValueError(
                "Orchestrator.run() only runs a single simulated day. "
                "For multi-day protocols use MultiDayRunner "
                "(synthetic_socio_wind_tunnel.orchestrator.multi_day). "
                "Construct Orchestrator with num_days=1 here."
            )
        if not isinstance(tick_minutes, int) or tick_minutes <= 0:
            raise ValueError(f"tick_minutes must be a positive integer, got {tick_minutes}")
        if 1440 % tick_minutes != 0:
            raise ValueError(
                f"tick_minutes ({tick_minutes}) must evenly divide 1440 (24*60); "
                f"valid choices include 1/2/3/4/5/6/8/10/12/15/20/30/60."
            )

        self._atlas = atlas
        self._ledger = ledger
        self._agents = list(agents)
        self._attention_service = attention_service
        self._tick_minutes = tick_minutes
        # add-walking-speed-budget: 80 m/min = 5 km/h average walk; 5-min
        # tick → 400m max travel per tick. Prevents the "agent walks 22
        # street segments in 5 min" teleport bug.
        self._walking_speed_m_per_min = max(1.0, walking_speed_m_per_min)
        self._ticks_per_day = 1440 // tick_minutes
        self._seed = seed
        self._num_days = num_days

        self._simulation = simulation or SimulationService(atlas, ledger)
        self._navigation = navigation or NavigationService(atlas, ledger)
        self._pipeline = pipeline or self._default_pipeline()
        self._resolver = IntentResolver(seed=seed)
        self._hooks: dict[HookName, list[Callable]] = {name: [] for name in _HOOK_NAMES}
        # ai-town port (Phase E task 20): async on_tick_end hooks for
        # OperationPool.process_pending. Run AFTER sync on_tick_end hooks
        # so synchronous metrics / replan see the same TickResult first.
        self._async_tick_end_hooks: list[
            Callable[[TickResult], Awaitable[None]]
        ] = []

        # 2026-05-21 H3 (persistent-asyncio-loop): single event loop
        # reused across all ticks. Prevents httpx.AsyncClient
        # cross-loop state corruption that manifested as the recurring
        # 1.5h-hang at publishable scale (backlog 1.9, scout 2026-05-20).
        # Lazy-initialized on first _fire_async_tick_end. Closed in
        # _fire("on_simulation_end").
        self._persistent_loop: asyncio.AbstractEventLoop | None = None

    def _default_pipeline(self) -> PerceptionPipeline:
        return PerceptionPipeline(
            self._atlas,
            self._ledger,
            include_digital_filter=self._attention_service is not None,
            attention_service=self._attention_service,
        )

    # ---- Hook registration ----

    def register_on_simulation_start(self, cb: Callable[[SimulationContext], None]) -> None:
        self._hooks["on_simulation_start"].append(cb)

    def register_on_tick_start(self, cb: Callable[[TickContext], None]) -> None:
        self._hooks["on_tick_start"].append(cb)

    def register_on_tick_end(self, cb: Callable[[TickResult], None]) -> None:
        self._hooks["on_tick_end"].append(cb)

    def register_on_tick_end_async(
        self, cb: Callable[[TickResult], Awaitable[None]],
    ) -> None:
        """Register an async coroutine factory to run AFTER sync on_tick_end hooks.

        Use this for the OperationPool.process_pending sweep: it returns a
        coroutine that completes any in-flight LLM ops and routes results
        back to per-agent tick_inputs queues. Multiple async hooks fire
        sequentially within `asyncio.run`; failure in one does not abort
        the others.
        """
        self._async_tick_end_hooks.append(cb)

    def register_on_simulation_end(self, cb: Callable[[SimulationSummary], None]) -> None:
        self._hooks["on_simulation_end"].append(cb)

    def _fire(self, name: HookName, payload) -> None:
        for cb in self._hooks[name]:
            cb(payload)

    def _fire_async_tick_end(self, tick_result: TickResult) -> None:
        """Run all registered async on_tick_end hooks on a persistent
        event loop (H3 2026-05-21 persistent-asyncio-loop).

        Lazy-creates the loop on first call. Reuses the SAME loop
        across all subsequent invocations to avoid the httpx.AsyncClient
        cross-loop state corruption that manifested as the recurring
        1.5h-hang at publishable scale (backlog 1.9 + scout 2026-05-20).

        Loop is closed in `on_simulation_end` (see Orchestrator.run end).
        """
        if not self._async_tick_end_hooks:
            return

        async def runner() -> None:
            for hook in self._async_tick_end_hooks:
                try:
                    await hook(tick_result)
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "async on_tick_end hook %r raised: %r",
                        hook, exc,
                    )

        # Lazy-create / reuse persistent loop
        if self._persistent_loop is None or self._persistent_loop.is_closed():
            self._persistent_loop = asyncio.new_event_loop()
        loop = self._persistent_loop
        try:
            loop.run_until_complete(runner())
        except RuntimeError as exc:
            # Defensive: if loop got into bad state, rebuild it for next tick
            logging.getLogger(__name__).warning(
                "persistent loop run_until_complete failed (%r); "
                "rebuilding loop for next tick", exc,
            )
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass
            self._persistent_loop = asyncio.new_event_loop()
            try:
                self._persistent_loop.run_until_complete(runner())
            except Exception as exc2:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "rebuilt persistent loop also failed (%r); "
                    "skipping this tick's async hooks", exc2,
                )

    def _close_persistent_loop(self) -> None:
        """H3 (2026-05-21): close the persistent loop at simulation end.
        Idempotent. Called from on_simulation_end hook chain."""
        if self._persistent_loop is None:
            return
        try:
            if not self._persistent_loop.is_closed():
                # Cancel any remaining tasks
                pending = asyncio.all_tasks(self._persistent_loop)
                for t in pending:
                    t.cancel()
                self._persistent_loop.close()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "persistent loop close failed (%r); proceeding", exc,
            )

    # ---- Main entry ----

    def run(
        self,
        *,
        day_index: int = 0,
        simulated_date: date | None = None,
        start_tick: int = 0,
    ) -> SimulationSummary:
        """
        跑完一天 288 tick (或从 start_tick 跑到日末)。

        - `day_index` 默认 0（单日调用）；`MultiDayRunner` 按 0, 1, 2, ... 传入
        - `simulated_date` 未传时从 `Ledger.current_time.date()` 派生
        - 两者被填入 TickContext / TickResult / CommitRecord /
          SimulationContext / SimulationSummary，但**不影响**单日行为
        - `start_tick` (2026-05-21 mid-day-resume, closes backlog 1.16):
          mid-day resume 时跳过已完成的 tick。Fresh run = 0；snap-resume
          时由 MultiDayRunner 传入 `snap.tick_index_in_day + 1`。range
          变为 `range(start_tick, num_ticks)`。
        """
        started_at = datetime.now()
        resolved_date = simulated_date or self._ledger.current_time.date()
        sim_ctx = SimulationContext(
            num_days=self._num_days,
            ticks_per_day=self._ticks_per_day,
            tick_minutes=self._tick_minutes,
            seed=self._seed,
            agent_ids=tuple(sorted(a.profile.agent_id for a in self._agents)),
            started_at=started_at,
            simulated_date=resolved_date,
            day_index=day_index,
        )
        self._fire("on_simulation_start", sim_ctx)

        total_commits_succeeded = 0
        total_commits_failed = 0
        total_encounters = 0
        num_ticks = self._ticks_per_day * self._num_days

        # agent_id → AgentRuntime lookup, sorted for deterministic iteration
        agents_by_id = {a.profile.agent_id: a for a in self._agents}
        sorted_agent_ids = tuple(sorted(agents_by_id.keys()))

        if not (0 <= start_tick <= num_ticks):
            raise ValueError(
                f"start_tick={start_tick} out of bounds for "
                f"num_ticks={num_ticks} (day_index={day_index})"
            )
        for tick_index in range(start_tick, num_ticks):
            tick_result = self._run_tick(
                tick_index,
                agents_by_id,
                sorted_agent_ids,
                day_index=day_index,
                simulated_date=resolved_date,
            )
            for commit in tick_result.commits:
                if commit.result.success:
                    total_commits_succeeded += 1
                else:
                    total_commits_failed += 1
            total_encounters += len(tick_result.encounter_candidates)
            self._fire("on_tick_end", tick_result)
            # ai-town port: async hooks (OperationPool.process_pending)
            # fire AFTER sync hooks so process_tick / metrics see results first.
            self._fire_async_tick_end(tick_result)

        ended_at = datetime.now()
        # total_ticks reflects actual ticks executed (excludes
        # already-completed ticks skipped via start_tick on mid-day
        # resume). Fresh runs have start_tick=0 → unchanged.
        summary = SimulationSummary(
            total_ticks=num_ticks - start_tick,
            total_encounters=total_encounters,
            total_commits_succeeded=total_commits_succeeded,
            total_commits_failed=total_commits_failed,
            seed=self._seed,
            started_at=started_at,
            ended_at=ended_at,
            simulated_date=resolved_date,
            day_index=day_index,
        )
        self._fire("on_simulation_end", summary)
        # 2026-05-21 H3 (persistent-asyncio-loop): close the persistent
        # loop after all on_simulation_end hooks fire (in case any
        # cleanup hook needs to schedule async work, give it the chance).
        self._close_persistent_loop()
        return summary

    # ---- One tick ----

    def _run_tick(
        self,
        tick_index: int,
        agents_by_id: dict[str, "AgentRuntime"],
        sorted_agent_ids: tuple[str, ...],
        *,
        day_index: int = 0,
        simulated_date: date | None = None,
    ) -> TickResult:
        tick_start_time = self._ledger.current_time
        resolved_date = simulated_date or tick_start_time.date()

        # 1. on_tick_start — fires ONCE before any per-agent work
        start_ctx = TickContext(
            tick_index=tick_index,
            simulated_time=tick_start_time,
            observer_context=None,
            simulated_date=resolved_date,
            day_index=day_index,
        )
        self._fire("on_tick_start", start_ctx)

        # 2. Observation + agent.step() per agent
        intent_pool: dict[str, Intent] = {}
        for agent_id in sorted_agent_ids:
            agent = agents_by_id[agent_id]
            observer_ctx = self._build_observer_context(agent)
            tick_ctx = TickContext(
                tick_index=tick_index,
                simulated_time=tick_start_time,
                observer_context=observer_ctx,
                simulated_date=resolved_date,
                day_index=day_index,
            )
            intent_pool[agent_id] = agent.step(tick_ctx)

        # 3. Resolve
        decisions = self._resolver.resolve(intent_pool)

        # 4. Commit
        commits: list[CommitRecord] = []
        traces: dict[str, TickMovementTrace] = {}

        for decision in decisions:
            agent = agents_by_id[decision.agent_id]
            if decision.status == "rejected":
                result = SimulationResult.fail(
                    f"Intent rejected: {decision.reason}",
                    error_code=SimulationErrorCode.PRECONDITION_FAILED,
                )
                commits.append(CommitRecord(
                    agent_id=decision.agent_id,
                    intent=decision.intent,
                    result=result,
                    simulated_date=resolved_date,
                    day_index=day_index,
                ))
                continue

            result, trace = self._dispatch(decision.agent_id, decision.intent, agent)
            commits.append(CommitRecord(
                agent_id=decision.agent_id,
                intent=decision.intent,
                result=result,
                simulated_date=resolved_date,
                day_index=day_index,
            ))
            if trace is not None:
                traces[decision.agent_id] = trace

        # 5. Encounter detection — pass end-of-tick entity locations to
        # capture co-presence of stationary agents (B9 fix).
        entity_locations: dict[str, str] = {}
        for ent_id in self._ledger.list_entity_ids():
            ent = self._ledger.get_entity(ent_id)
            if ent is not None and ent.location_id:
                entity_locations[ent_id] = ent.location_id
        encounter_candidates = self._detect_encounters(
            tick_index, traces, entity_locations=entity_locations,
        )

        # 6. Advance time
        self._ledger.current_time = tick_start_time + timedelta(minutes=self._tick_minutes)

        # 7. Build TickResult (on_tick_end fires in run() to centralize stat collection)
        movement_traces_tuple = tuple(
            (agent_id, trace.locations)
            for agent_id, trace in traces.items()
            if trace and trace.locations
        )
        return TickResult(
            tick_index=tick_index,
            simulated_time=tick_start_time,
            commits=tuple(commits),
            encounter_candidates=tuple(encounter_candidates),
            simulated_date=resolved_date,
            day_index=day_index,
            entity_locations=tuple(entity_locations.items()),
            movement_traces=movement_traces_tuple,
        )

    # ---- Observer context with position bridge (D11) ----

    def _build_observer_context(self, agent: "AgentRuntime") -> ObserverContext:
        ctx_dict = agent.build_observer_context()
        entity = self._ledger.get_entity(agent.profile.agent_id)
        ctx_dict["position"] = entity.position if entity else Coord(x=0.0, y=0.0)
        # agent.build_observer_context() already sets location_id from runtime.
        # Some defaults we expect from ObserverContext: entity_id, position, location_id.
        return ObserverContext(**ctx_dict)

    # ---- Intent dispatch (D9) ----

    def _dispatch(
        self,
        agent_id: str,
        intent: Intent,
        agent: "AgentRuntime",
    ) -> tuple[SimulationResult, TickMovementTrace | None]:
        """Return (result, trace-or-None). Trace only populated for MoveIntent."""
        if isinstance(intent, WaitIntent):
            return SimulationResult.ok(message=f"wait:{intent.reason}"), None

        if isinstance(intent, MoveIntent):
            return self._dispatch_move(agent_id, intent, agent)

        if isinstance(intent, ExamineIntent):
            self._simulation.mark_item_examined(intent.target, agent_id)
            return SimulationResult.ok(message=f"examined:{intent.target}"), None

        if isinstance(intent, PickupIntent):
            result = self._simulation.give_item_to_entity(intent.item_id, agent_id)
            return result, None

        if isinstance(intent, OpenDoorIntent):
            result = self._simulation.open_door(intent.door_id, agent_id)
            return result, None

        if isinstance(intent, UnlockIntent):
            result = self._simulation.unlock_door(intent.door_id, agent_id, intent.key_id)
            return result, None

        if isinstance(intent, LockIntent):
            result = self._simulation.lock_door(intent.door_id, agent_id, intent.key_id)
            return result, None

        return SimulationResult.fail(
            f"Unknown intent type: {type(intent).__name__}",
            error_code=SimulationErrorCode.INVALID_OPERATION,
        ), None

    def _dispatch_move(
        self,
        agent_id: str,
        intent: MoveIntent,
        agent: "AgentRuntime",
    ) -> tuple[SimulationResult, TickMovementTrace | None]:
        """
        MoveIntent 展开 (add-walking-speed-budget): advance the agent along
        NavigationService route subject to a per-tick distance budget so a
        long route spreads across multiple ticks instead of teleporting.

        Budget = tick_minutes × walking_speed_m_per_min (default 5 × 80 = 400m).
        Remaining route steps are cached on `agent._in_flight_route_remaining`
        so the next tick resumes walking from where this one stopped.
        """
        from_loc = agent.current_location
        if from_loc == intent.to_location:
            # Already there — clear any stale in-flight state
            agent._in_flight_route_remaining = []
            agent._in_flight_target = None
            return SimulationResult.ok(message="already_at_location"), None

        # Resume in-flight walk if same target; else recompute route
        if (agent._in_flight_target == intent.to_location
                and agent._in_flight_route_remaining):
            steps_to_walk = list(agent._in_flight_route_remaining)
        else:
            # add-walking-speed-budget: filter route by transport mode so
            # car-less agents skip motorway-only segments and driving agents
            # avoid footpaths.
            agent_mode = (
                "driving" if getattr(agent.profile, "prefer_driving", False)
                else "walking"
            )
            route = self._navigation.find_route(
                from_loc, intent.to_location, mode=agent_mode,
            )
            if not route.success or not route.steps:
                # Fall back to mode='any' so we don't fail just because of
                # mode filter — agent will still respect speed budget per tick.
                route = self._navigation.find_route(from_loc, intent.to_location)
            if not route.success or not route.steps:
                agent._in_flight_route_remaining = []
                agent._in_flight_target = None
                return SimulationResult.fail(
                    f"Route not found: {route.error or 'no steps'}",
                    error_code=SimulationErrorCode.LOCATION_UNREACHABLE,
                ), None
            steps_to_walk = list(route.steps)
            agent._in_flight_target = intent.to_location

        # C3 fix: per-trip mode override. Driver going to a near destination
        # (< 500m straight-line) defaults to walking pace instead of driving.
        # Captures "1-car household walks to grocery, drives to work" behavior.
        agent_speed = float(getattr(
            agent.profile, "walking_speed_m_per_min",
            self._walking_speed_m_per_min,
        ) or self._walking_speed_m_per_min)
        prefer_driving = getattr(agent.profile, "prefer_driving", False)
        if prefer_driving:
            home_c = self._atlas.get_center(from_loc)
            dest_c = self._atlas.get_center(intent.to_location)
            if home_c and dest_c:
                straight_line_m = (
                    (home_c.x - dest_c.x) ** 2 + (home_c.y - dest_c.y) ** 2
                ) ** 0.5
                # Short trip → walk pace (overrides driver baseline)
                if straight_line_m < 500.0:
                    agent_speed = 80.0
        tick_budget_m = self._tick_minutes * agent_speed
        trace_locations: list[str] = []
        consumed_distance = 0.0
        last_result = SimulationResult.ok(message="no_steps")
        idx = 0
        for nav_step in steps_to_walk:
            step_distance = float(getattr(nav_step, "distance", 0.0) or 0.0)
            step_location = nav_step.to_location
            result = self._simulation.move_entity(agent_id, step_location)
            if not result.success:
                last_result = result
                break
            agent.current_location = step_location
            trace_locations.append(step_location)
            last_result = result
            consumed_distance += step_distance
            idx += 1
            # Stop after current step if we've already used the tick's budget.
            # Always advance at least 1 step per tick (avoids stuck-at-zero
            # when one segment alone exceeds budget).
            if consumed_distance >= tick_budget_m:
                break

        # Save remaining for next tick; clear if route done
        remaining = steps_to_walk[idx:]
        if remaining:
            agent._in_flight_route_remaining = remaining
        else:
            agent._in_flight_route_remaining = []
            agent._in_flight_target = None

        trace = (
            TickMovementTrace(locations=tuple(trace_locations))
            if trace_locations else None
        )
        return last_result, trace

    # ---- Encounter detection ----

    def _detect_encounters(
        self,
        tick_index: int,
        traces: dict[str, TickMovementTrace],
        entity_locations: dict[str, str] | None = None,
    ) -> list[EncounterCandidate]:
        """
        Two sources fed into a per-location bucket:

        1. **trace-based** — for agents who moved this tick, every sub-step
           location in their TickMovementTrace.
        2. **end-of-tick co-presence** — `entity_locations[agent_id]` is each
           agent's `current_location` at tick end (from Ledger snapshot),
           covers stationary agents (WaitIntent / no movement).

        B9 fix (fix-encounter-detection-and-observability, 2026-05-10): without
        source (2), agents dwelling at a location were invisible to encounter
        detection — systematically undercount encounters during dwell windows.

        O(total_trace_length + N) — N = number of entities.
        """
        location_visitors: dict[str, set[str]] = defaultdict(set)

        # Source 1: trace-based (walking through)
        for agent_id, trace in traces.items():
            for loc in trace.locations:
                location_visitors[loc].add(agent_id)

        # Source 2: end-of-tick co-presence (stationary + walking-arrived)
        if entity_locations:
            for agent_id, loc in entity_locations.items():
                if loc:
                    location_visitors[loc].add(agent_id)

        if not location_visitors:
            return []

        # Collect pair → shared locations
        pair_shared: dict[tuple[str, str], set[str]] = defaultdict(set)
        for loc, visitors in location_visitors.items():
            if len(visitors) < 2:
                continue
            sorted_visitors = sorted(visitors)
            for i in range(len(sorted_visitors)):
                for j in range(i + 1, len(sorted_visitors)):
                    pair_shared[(sorted_visitors[i], sorted_visitors[j])].add(loc)

        candidates: list[EncounterCandidate] = []
        for (a, b), shared_set in sorted(pair_shared.items()):
            candidates.append(EncounterCandidate(
                tick=tick_index,
                agent_a=a,
                agent_b=b,
                shared_locations=tuple(sorted(shared_set)),
            ))
        return candidates
