"""
Orchestrator 数据模型 — frozen dataclasses。

所有结构不含 Ledger / Atlas 引用，便于 hook 订阅者持有 / 序列化 / 跨进程传输。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.intent import Intent
    from synthetic_socio_wind_tunnel.engine.simulation import SimulationResult
    from synthetic_socio_wind_tunnel.perception.models import ObserverContext


HookName = Literal[
    "on_simulation_start",
    "on_tick_start",
    "on_tick_end",
    "on_simulation_end",
]


@dataclass(frozen=True)
class TickContext:
    """
    tick 级上下文。

    - 在 `on_tick_start` hook 触发时：`observer_context=None`
      （tick 还没开始 per-agent 感知）。
    - 在 `AgentRuntime.step(ctx)` 时：`observer_context` 是该 agent 自己的
      ObserverContext（已含 digital_state / position 等）。

    `simulated_date` 与 `day_index` 由 multi-day 路径填充；单日调用时
    orchestrator 从 Ledger.current_time.date() 派生 simulated_date，
    day_index 默认 0。
    """

    tick_index: int
    simulated_time: datetime
    observer_context: "ObserverContext | None" = None
    simulated_date: date | None = None
    day_index: int = 0


@dataclass(frozen=True)
class CommitRecord:
    """单个 agent 在本 tick 的 Intent 提交记录。"""

    agent_id: str
    intent: "Intent"
    result: "SimulationResult"
    simulated_date: date | None = None
    day_index: int = 0


@dataclass(frozen=True)
class EncounterCandidate:
    """tick 内路径交集的相遇候选对。by convention agent_a < agent_b 字典序。"""

    tick: int
    agent_a: str
    agent_b: str
    shared_locations: tuple[str, ...]


@dataclass(frozen=True)
class TickMovementTrace:
    """orchestrator 内部状态；tick 末被扫描后丢弃。"""

    locations: tuple[str, ...]

    def extend(self, loc: str) -> "TickMovementTrace":
        """返回追加 location 的新 trace（frozen 下的不可变式"追加"）。"""
        return TickMovementTrace(locations=self.locations + (loc,))


@dataclass(frozen=True)
class TickResult:
    """on_tick_end hook 订阅者收到的结构。"""

    tick_index: int
    simulated_time: datetime
    commits: tuple[CommitRecord, ...]
    encounter_candidates: tuple[EncounterCandidate, ...]
    simulated_date: date | None = None
    day_index: int = 0


@dataclass(frozen=True)
class SimulationContext:
    """on_simulation_start hook 订阅者收到的结构。"""

    num_days: int
    ticks_per_day: int
    tick_minutes: int
    seed: int
    agent_ids: tuple[str, ...]
    started_at: datetime
    simulated_date: date | None = None
    day_index: int = 0


@dataclass(frozen=True)
class SimulationSummary:
    """on_simulation_end hook + Orchestrator.run() 返回值。"""

    total_ticks: int
    total_encounters: int
    total_commits_succeeded: int
    total_commits_failed: int
    seed: int
    started_at: datetime
    ended_at: datetime
    simulated_date: date | None = None
    day_index: int = 0
