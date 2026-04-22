"""
MultiDayRunner — 跨日 simulation 主入口。

分层（见 multi-day-simulation design D1）：
    Orchestrator         负责 1 天内的 288 tick 循环 + hook
    MultiDayRunner       负责 N 天的 day-by-day 调度 + on_day_* hook
                         + 调用方自选的 memory / planner 接入

调用方典型 pattern：

    runner = MultiDayRunner(orchestrator=orch, memory_service=memory,
                            planner=planner, seed=42)
    result = runner.run_multi_day(
        start_date=date(2026, 4, 22),
        num_days=14,
        on_day_start=lambda d, i: ...,   # 可选：外部 phase 切换逻辑
        on_day_end=lambda d, i, batch: ...,
    )
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Literal

from synthetic_socio_wind_tunnel.orchestrator.models import SimulationSummary

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.planner import LLMClient, Planner
    from synthetic_socio_wind_tunnel.agent.runtime import AgentRuntime
    from synthetic_socio_wind_tunnel.memory.models import DailySummary
    from synthetic_socio_wind_tunnel.memory.service import MemoryService
    from synthetic_socio_wind_tunnel.orchestrator.service import Orchestrator


RunMode = Literal["dev", "publishable"]

_DEV_MAX_DAYS = 3


@dataclass(frozen=True)
class DayRunSummary:
    """单日 run 的聚合结构。"""

    day_index: int
    simulated_date: date
    tick_count: int
    commit_succeeded: int
    commit_failed: int
    encounter_count: int
    daily_summary_batch: dict[str, "DailySummary"] = field(default_factory=dict)
    """agent_id → DailySummary；若 memory_service 未挂入则为空。"""


@dataclass(frozen=True)
class MultiDayResult:
    """整个 N 天 run 的返回值。"""

    per_day_summaries: tuple[DayRunSummary, ...]
    total_ticks: int
    total_encounters: int
    seed: int
    started_at: datetime
    ended_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    """预留给未来 metrics change 填充。"""

    def model_dump(self) -> dict[str, Any]:
        """JSON-safe 导出；dataclass 不自带，此处手动实现保持与 Pydantic 一致体验。"""
        return {
            "per_day_summaries": [
                {
                    "day_index": d.day_index,
                    "simulated_date": d.simulated_date.isoformat(),
                    "tick_count": d.tick_count,
                    "commit_succeeded": d.commit_succeeded,
                    "commit_failed": d.commit_failed,
                    "encounter_count": d.encounter_count,
                    "daily_summary_batch": {
                        aid: {
                            "agent_id": s.agent_id,
                            "date": s.date,
                            "summary_text": s.summary_text,
                        }
                        for aid, s in d.daily_summary_batch.items()
                    },
                }
                for d in self.per_day_summaries
            ],
            "total_ticks": self.total_ticks,
            "total_encounters": self.total_encounters,
            "seed": self.seed,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def combine(cls, results: list["MultiDayResult"]) -> "MultiDayAggregate":
        """跨 seed 聚合，产出 median / IQR / CI 统计字段。"""
        return MultiDayAggregate.from_results(results)


@dataclass(frozen=True)
class MultiDayAggregate:
    """N 个 seed 的 MultiDayResult 聚合。"""

    seed_count: int
    per_day_encounter_stats: tuple[dict[str, float], ...]
    """按 day_index 一条 dict：median / iqr_lo / iqr_hi / ci95_lo / ci95_hi。"""
    total_encounter_stats: dict[str, float]
    total_ticks_stats: dict[str, float]
    seeds: tuple[int, ...]

    @classmethod
    def from_results(cls, results: list[MultiDayResult]) -> "MultiDayAggregate":
        if not results:
            raise ValueError("MultiDayAggregate.from_results requires at least one MultiDayResult")

        # 假设所有 result 有相同 per_day_summaries 长度
        num_days = len(results[0].per_day_summaries)
        for r in results:
            if len(r.per_day_summaries) != num_days:
                raise ValueError(
                    "All MultiDayResult must have identical num_days for combine(); "
                    f"got {len(r.per_day_summaries)} and {num_days}"
                )

        per_day_stats = []
        for day_i in range(num_days):
            enc_series = [r.per_day_summaries[day_i].encounter_count for r in results]
            per_day_stats.append(_series_stats(enc_series))

        return cls(
            seed_count=len(results),
            per_day_encounter_stats=tuple(per_day_stats),
            total_encounter_stats=_series_stats([r.total_encounters for r in results]),
            total_ticks_stats=_series_stats([r.total_ticks for r in results]),
            seeds=tuple(r.seed for r in results),
        )

    def model_dump(self) -> dict[str, Any]:
        return {
            "seed_count": self.seed_count,
            "seeds": list(self.seeds),
            "per_day_encounter_stats": [dict(s) for s in self.per_day_encounter_stats],
            "total_encounter_stats": dict(self.total_encounter_stats),
            "total_ticks_stats": dict(self.total_ticks_stats),
        }


def _series_stats(series: list[int] | list[float]) -> dict[str, float]:
    """单一序列 → median / IQR / 95% CI（非正态保守近似）。"""
    if not series:
        return {"median": 0.0, "iqr_lo": 0.0, "iqr_hi": 0.0, "ci95_lo": 0.0, "ci95_hi": 0.0}
    s = sorted(series)
    n = len(s)

    def _pctl(p: float) -> float:
        # 线性插值 percentile（不引入 numpy 依赖）
        if n == 1:
            return float(s[0])
        idx = p * (n - 1)
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return float(s[lo])
        frac = idx - lo
        return float(s[lo]) + (float(s[hi]) - float(s[lo])) * frac

    median = _pctl(0.5)
    iqr_lo = _pctl(0.25)
    iqr_hi = _pctl(0.75)
    # 保守 95% CI：用 2.5% / 97.5% percentile（非参数 bootstrap 简化版）
    ci95_lo = _pctl(0.025)
    ci95_hi = _pctl(0.975)
    return {
        "median": median,
        "iqr_lo": iqr_lo,
        "iqr_hi": iqr_hi,
        "ci95_lo": ci95_lo,
        "ci95_hi": ci95_hi,
    }


class MultiDayRunner:
    """驱动 N 日 simulation 的主类。"""

    __slots__ = (
        "_orchestrator",
        "_memory_service",
        "_planner",
        "_llm_client",
        "_seed",
        "_mode",
    )

    def __init__(
        self,
        *,
        orchestrator: "Orchestrator",
        memory_service: "MemoryService | None" = None,
        planner: "Planner | None" = None,
        llm_client: "LLMClient | None" = None,
        seed: int = 0,
        mode: RunMode = "publishable",
    ) -> None:
        """
        Args:
            orchestrator: per-day 引擎；每日复用
            memory_service: 若提供，每日末调 run_daily_summary + 派生
                CarryoverContext 供次日 planner 使用
            planner: 若提供 + 提供 llm_client，每日初重新生成 plan
            llm_client: planner 与 memory_service.run_daily_summary 共用
            seed: 传入 MultiDayResult 字段记录
            mode: "dev"（限 3 天）或 "publishable"（无上限）
        """
        self._orchestrator = orchestrator
        self._memory_service = memory_service
        self._planner = planner
        self._llm_client = llm_client
        self._seed = seed
        self._mode = mode

    @property
    def mode(self) -> RunMode:
        return self._mode

    def run_multi_day(
        self,
        *,
        start_date: date,
        num_days: int,
        on_day_start: Callable[[date, int], None] | None = None,
        on_day_end: Callable[[date, int, dict[str, "DailySummary"]], None] | None = None,
    ) -> MultiDayResult:
        """按天推进 num_days 天的 simulation。"""
        if num_days < 1:
            raise ValueError(f"num_days must be >= 1, got {num_days}")
        if self._mode == "dev" and num_days > _DEV_MAX_DAYS:
            raise ValueError(
                f"dev mode limited to {_DEV_MAX_DAYS} days; use mode='publishable' "
                f"for 14-day protocol (got num_days={num_days})"
            )

        started_at = datetime.now()
        per_day: list[DayRunSummary] = []
        total_ticks = 0
        total_encounters = 0

        # 导入 agents 映射给 memory carryover 使用
        agents_by_id = self._collect_agents()

        for day_index in range(num_days):
            current_date = start_date + timedelta(days=day_index)

            # on_day_start: 先让外部 hook 决定 phase / intervention on/off
            if on_day_start is not None:
                on_day_start(current_date, day_index)

            # 内置：若 planner + llm_client 都在，生成次日 plan 并挂到 runtime
            if self._planner is not None and self._llm_client is not None:
                self._generate_plans_for_day(
                    agents_by_id,
                    current_date=current_date,
                    day_index=day_index,
                )

            # 一日 tick 循环
            day_summary = self._orchestrator.run(
                day_index=day_index,
                simulated_date=current_date,
            )

            # 内置：若 memory_service + llm_client 都在，跑 daily summary
            batch: dict[str, "DailySummary"] = {}
            if self._memory_service is not None and self._llm_client is not None:
                batch = asyncio.run(
                    self._memory_service.run_daily_summary(
                        agents_by_id, self._llm_client,
                    )
                )

            # on_day_end: 外部 hook 可读 batch 做 metrics 采集 / phase 转
            if on_day_end is not None:
                on_day_end(current_date, day_index, batch)

            total_ticks += day_summary.total_ticks
            total_encounters += day_summary.total_encounters

            per_day.append(DayRunSummary(
                day_index=day_index,
                simulated_date=current_date,
                tick_count=day_summary.total_ticks,
                commit_succeeded=day_summary.total_commits_succeeded,
                commit_failed=day_summary.total_commits_failed,
                encounter_count=day_summary.total_encounters,
                daily_summary_batch=batch,
            ))

        ended_at = datetime.now()
        return MultiDayResult(
            per_day_summaries=tuple(per_day),
            total_ticks=total_ticks,
            total_encounters=total_encounters,
            seed=self._seed,
            started_at=started_at,
            ended_at=ended_at,
            metadata={"mode": self._mode},
        )

    # ---- internals ----

    def _collect_agents(self) -> dict[str, "AgentRuntime"]:
        """从 orchestrator 拿 agent 映射。"""
        # Orchestrator 私有 _agents；通过 profile.agent_id 索引
        return {a.profile.agent_id: a for a in self._orchestrator._agents}

    def _generate_plans_for_day(
        self,
        agents_by_id: dict[str, "AgentRuntime"],
        *,
        current_date: date,
        day_index: int,
    ) -> None:
        """为每个 agent 生成当天的 plan，注入 carryover context。"""
        assert self._planner is not None
        assert self._llm_client is not None

        async def _one(agent: "AgentRuntime") -> None:
            # 仅当 memory_service 存在时才构造 carryover；否则 plan 从 profile 生成
            carryover = None
            if self._memory_service is not None:
                carryover = self._memory_service.get_carryover_context(
                    agent.profile.agent_id,
                    current_day_index=day_index,
                )
            plan = await self._planner.generate_daily_plan(
                agent.profile,
                date=current_date.isoformat(),
                carryover=carryover,
            )
            agent.plan = plan

        async def _all() -> None:
            await asyncio.gather(*(_one(a) for a in agents_by_id.values()))

        asyncio.run(_all())


__all__ = [
    "MultiDayRunner",
    "MultiDayResult",
    "MultiDayAggregate",
    "DayRunSummary",
    "RunMode",
]
