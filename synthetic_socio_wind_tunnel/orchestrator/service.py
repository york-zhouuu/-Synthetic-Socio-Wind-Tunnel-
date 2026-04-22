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

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Callable

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
        self._ticks_per_day = 1440 // tick_minutes
        self._seed = seed
        self._num_days = num_days

        self._simulation = simulation or SimulationService(atlas, ledger)
        self._navigation = navigation or NavigationService(atlas, ledger)
        self._pipeline = pipeline or self._default_pipeline()
        self._resolver = IntentResolver(seed=seed)
        self._hooks: dict[HookName, list[Callable]] = {name: [] for name in _HOOK_NAMES}

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

    def register_on_simulation_end(self, cb: Callable[[SimulationSummary], None]) -> None:
        self._hooks["on_simulation_end"].append(cb)

    def _fire(self, name: HookName, payload) -> None:
        for cb in self._hooks[name]:
            cb(payload)

    # ---- Main entry ----

    def run(
        self,
        *,
        day_index: int = 0,
        simulated_date: date | None = None,
    ) -> SimulationSummary:
        """
        跑完一天 288 tick。

        - `day_index` 默认 0（单日调用）；`MultiDayRunner` 按 0, 1, 2, ... 传入
        - `simulated_date` 未传时从 `Ledger.current_time.date()` 派生
        - 两者被填入 TickContext / TickResult / CommitRecord /
          SimulationContext / SimulationSummary，但**不影响**单日行为
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

        for tick_index in range(num_ticks):
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

        ended_at = datetime.now()
        summary = SimulationSummary(
            total_ticks=num_ticks,
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

        # 5. Encounter detection
        encounter_candidates = self._detect_encounters(tick_index, traces)

        # 6. Advance time
        self._ledger.current_time = tick_start_time + timedelta(minutes=self._tick_minutes)

        # 7. Build TickResult (on_tick_end fires in run() to centralize stat collection)
        return TickResult(
            tick_index=tick_index,
            simulated_time=tick_start_time,
            commits=tuple(commits),
            encounter_candidates=tuple(encounter_candidates),
            simulated_date=resolved_date,
            day_index=day_index,
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
        MoveIntent 展开：NavigationService.find_route → 逐 step move_entity。
        每 sub-step 的成功 location 追加到 TickMovementTrace。
        """
        from_loc = agent.current_location
        if from_loc == intent.to_location:
            # Already there — no move, no trace (won't produce encounters either)
            return SimulationResult.ok(message="already_at_location"), None

        route = self._navigation.find_route(from_loc, intent.to_location)
        if not route.success or not route.steps:
            return SimulationResult.fail(
                f"Route not found: {route.error or 'no steps'}",
                error_code=SimulationErrorCode.LOCATION_UNREACHABLE,
            ), None

        # Walk each NavigationStep: each step has a to_location
        trace_locations: list[str] = []
        last_result = SimulationResult.ok(message="no_steps")
        for nav_step in route.steps:
            step_location = nav_step.to_location
            result = self._simulation.move_entity(agent_id, step_location)
            if not result.success:
                # Stop on failure; agent stays at last successful sub-step
                last_result = result
                break
            # Update agent's cached current_location so subsequent ticks see it
            agent.current_location = step_location
            trace_locations.append(step_location)
            last_result = result

        trace = TickMovementTrace(locations=tuple(trace_locations)) if trace_locations else None
        return last_result, trace

    # ---- Encounter detection ----

    def _detect_encounters(
        self,
        tick_index: int,
        traces: dict[str, TickMovementTrace],
    ) -> list[EncounterCandidate]:
        """
        O(total_trace_length): group agents by each visited location,
        emit pair (a, b) for any location shared.
        """
        if not traces:
            return []

        location_visitors: dict[str, set[str]] = defaultdict(set)
        for agent_id, trace in traces.items():
            for loc in trace.locations:
                location_visitors[loc].add(agent_id)

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
