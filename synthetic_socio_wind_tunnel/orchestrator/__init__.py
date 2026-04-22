"""
Orchestrator — Phase 2 的 tick 循环驱动

职责（刻意窄）：
- 每 tick 为每个 agent 走"感知 → 意图 → 裁决 → 提交"流程
- Intent 收集 + 独占类裁决（字典序）
- MoveIntent 逐 step 写 Ledger（启用 mid-tick 可见性）
- tick 末按 TickMovementTrace 产出 EncounterCandidate
- 单天循环；多天由 MultiDayRunner 逐日调用 run() 实现

**非**职责（由后续 Phase 2 change 填）：replan / LLM / metrics

见 openspec/specs/orchestrator/spec.md 与
    openspec/specs/multi-day-run/spec.md（若存在）
"""

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
from synthetic_socio_wind_tunnel.orchestrator.intent_resolver import (
    CommitDecision,
    IntentResolver,
)
from synthetic_socio_wind_tunnel.orchestrator.multi_day import (
    DayRunSummary,
    MultiDayAggregate,
    MultiDayResult,
    MultiDayRunner,
    RunMode,
)
from synthetic_socio_wind_tunnel.orchestrator.service import Orchestrator

__all__ = [
    "CommitDecision",
    "CommitRecord",
    "DayRunSummary",
    "EncounterCandidate",
    "HookName",
    "IntentResolver",
    "MultiDayAggregate",
    "MultiDayResult",
    "MultiDayRunner",
    "Orchestrator",
    "RunMode",
    "SimulationContext",
    "SimulationSummary",
    "TickContext",
    "TickMovementTrace",
    "TickResult",
]
