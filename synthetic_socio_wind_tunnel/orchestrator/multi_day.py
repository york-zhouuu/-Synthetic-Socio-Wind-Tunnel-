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
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

from synthetic_socio_wind_tunnel.orchestrator.models import SimulationSummary
from synthetic_socio_wind_tunnel.run_resilience import DayCheckpointWriter

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.planner import LLMClient, Planner
    from synthetic_socio_wind_tunnel.agent.runtime import AgentRuntime
    from synthetic_socio_wind_tunnel.memory.models import DailySummary
    from synthetic_socio_wind_tunnel.memory.service import MemoryService
    from synthetic_socio_wind_tunnel.orchestrator.service import Orchestrator


logger = logging.getLogger(__name__)


class _GracefulStop(Exception):
    """Internal signal: SIGUSR1 received, abort current day, write partial,
    return truncated MultiDayResult."""


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
    """驱动 N 日 simulation 的主类。

    run-resilience (2026-05-15): 接入 per-day checkpoint（每天 end 落
    partial JSON）+ resume_from（从指定 day 起跑）+ SIGUSR1 graceful-stop
    协议（外部把 `_graceful_stop_requested` 置 True，主循环在下个 tick 之前
    优雅终止）。"""

    __slots__ = (
        "_orchestrator",
        "_memory_service",
        "_attention_service",
        "_planner",
        "_llm_client",
        "_seed",
        "_mode",
        "_output_dir",
        "_checkpoint_writer",
        "_resume_from",
        "_provider_name",
        "_graceful_stop_requested",
        # tick-level-resume (2026-05-16)
        "_snapshot_policy",
        "_restore_from",
        "_wal_writer",
    )

    def __init__(
        self,
        *,
        orchestrator: "Orchestrator",
        memory_service: "MemoryService | None" = None,
        attention_service: Any = None,
        planner: "Planner | None" = None,
        llm_client: "LLMClient | None" = None,
        seed: int = 0,
        mode: RunMode = "publishable",
        output_dir: Path | None = None,
        checkpoint_writer: DayCheckpointWriter | None = None,
        resume_from: int = 0,
        provider_name: str = "unknown",
        snapshot_policy: Any = None,
        restore_from: Any = None,
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
            output_dir: per-day partial JSON 写盘目录；None 时禁用 checkpoint
            checkpoint_writer: 自定义 DayCheckpointWriter；None 时默认构造
            resume_from: 从该 day_index 开始跑（默认 0）；外部需在调用前
                把 partial 内容载回 in-memory state
            provider_name: 记录到 partial 元数据的 LLM provider
                ("gemini"/"deepseek"/"anthropic"/"stub")
        """
        if resume_from < 0:
            raise ValueError(f"resume_from must be >= 0, got {resume_from}")

        self._orchestrator = orchestrator
        self._memory_service = memory_service
        self._attention_service = attention_service
        self._planner = planner
        self._llm_client = llm_client
        self._seed = seed
        self._mode = mode
        self._output_dir = output_dir
        self._checkpoint_writer = (
            checkpoint_writer
            if checkpoint_writer is not None
            else (DayCheckpointWriter() if output_dir is not None else None)
        )
        self._resume_from = resume_from
        self._provider_name = provider_name
        self._graceful_stop_requested: bool = False

        # tick-level-resume (2026-05-16): snapshot/WAL policy + restore_from
        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            SnapshotPolicy,
        )
        self._snapshot_policy: SnapshotPolicy = (
            snapshot_policy if snapshot_policy is not None else SnapshotPolicy.from_env()
        )
        self._restore_from = restore_from  # SimulationCheckpoint | None
        self._wal_writer = None  # lazy-init in run_multi_day

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
        if self._resume_from > num_days:
            raise ValueError(
                f"resume_from ({self._resume_from}) exceeds num_days ({num_days})",
            )

        started_at = datetime.now()
        per_day: list[DayRunSummary] = []
        total_ticks = 0
        total_encounters = 0

        # 导入 agents 映射给 memory carryover 使用
        agents_by_id = self._collect_agents()

        # tick-level-resume: 若有 restore_from，先把 state 灌回各子系统
        effective_start_day = self._resume_from
        effective_start_tick_global = -1  # -1 = 起始时不存在前驱 tick
        if self._restore_from is not None:
            snap = self._restore_from
            if snap.day_index >= num_days:
                raise ValueError(
                    f"restore_from.day_index ({snap.day_index}) exceeds "
                    f"num_days ({num_days})",
                )
            snap.restore_into(
                ledger=getattr(self._orchestrator, "_ledger", None),
                agents=agents_by_id,
                memory_service=self._memory_service,
                attention_service=self._attention_service,
            )
            # restore_from 优先于 resume_from；继续从 (snap.day_index, snap.tick_index+1)
            if self._resume_from > 0:
                logger.warning(
                    "MultiDayRunner: restore_from supplied; resume_from=%d ignored",
                    self._resume_from,
                )
            effective_start_day = snap.day_index
            effective_start_tick_global = snap.tick_index
            logger.info(
                "MultiDayRunner: restored state from snapshot at day=%d "
                "tick_global=%d; resuming from next tick",
                snap.day_index, snap.tick_index,
            )

        # tick-level-resume: 初始化 WAL writer 与 snapshot 写盘 hook
        ticks_per_day = getattr(self._orchestrator, "_ticks_per_day", 288)
        self._init_wal_and_snapshot_hooks(ticks_per_day=ticks_per_day)

        # 注册 graceful-stop 检查 hook：每 tick 末检查 flag，True 时抛
        # _GracefulStop 中断当天剩余 tick。
        def _check_graceful(tick_result: Any) -> None:  # noqa: ARG001
            if self._graceful_stop_requested:
                raise _GracefulStop()

        self._orchestrator.register_on_tick_end(_check_graceful)
        try:
            for day_index in range(effective_start_day, num_days):
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

                # 一日 tick 循环 — 可能被 _GracefulStop 中断
                try:
                    day_summary = self._orchestrator.run(
                        day_index=day_index,
                        simulated_date=current_date,
                    )
                except _GracefulStop:
                    logger.warning(
                        "MultiDayRunner: SIGUSR1 graceful-stop received "
                        "at day_index=%d; aborting current day, writing "
                        "partial for last completed day, returning truncated result",
                        day_index,
                    )
                    self._write_partial_at_stop(
                        per_day=per_day, agents_by_id=agents_by_id,
                    )
                    break

                # 内置：若 memory_service + llm_client 都在，跑 daily summary
                batch: dict[str, "DailySummary"] = {}
                if self._memory_service is not None and self._llm_client is not None:
                    batch = asyncio.run(
                        self._memory_service.run_daily_summary(
                            agents_by_id, self._llm_client,
                        )
                    )

                total_ticks += day_summary.total_ticks
                total_encounters += day_summary.total_encounters

                day_run = DayRunSummary(
                    day_index=day_index,
                    simulated_date=current_date,
                    tick_count=day_summary.total_ticks,
                    commit_succeeded=day_summary.total_commits_succeeded,
                    commit_failed=day_summary.total_commits_failed,
                    encounter_count=day_summary.total_encounters,
                    daily_summary_batch=batch,
                )
                per_day.append(day_run)

                # Per-day checkpoint write — BEFORE on_day_end hook so external
                # consumers see a consistent partial on disk
                self._write_partial(
                    day_index=day_index,
                    simulated_date=current_date,
                    per_day=per_day,
                    agents_by_id=agents_by_id,
                )

                # on_day_end: 外部 hook 可读 batch 做 metrics 采集 / phase 转
                if on_day_end is not None:
                    on_day_end(current_date, day_index, batch)
        finally:
            # tick-level-resume: graceful-stop 时落 final snapshot（无论 N 整数倍）
            if self._graceful_stop_requested:
                self._write_final_snapshot_on_graceful_stop(
                    agents_by_id=agents_by_id,
                )
            # 清理 WAL writer（fsync + close）
            if self._wal_writer is not None:
                self._wal_writer.close()
                self._wal_writer = None
            # 清理 hook —— 防止多次 run_multi_day 累积 hooks（reaches into
            # Orchestrator._hooks because no public unregister exists yet）
            try:
                self._orchestrator._hooks["on_tick_end"].remove(_check_graceful)
            except (ValueError, KeyError, AttributeError):
                pass

        ended_at = datetime.now()
        return MultiDayResult(
            per_day_summaries=tuple(per_day),
            total_ticks=total_ticks,
            total_encounters=total_encounters,
            seed=self._seed,
            started_at=started_at,
            ended_at=ended_at,
            metadata={
                "mode": self._mode,
                "resume_from": self._resume_from,
                "graceful_stop": self._graceful_stop_requested,
            },
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

    # ---- tick-level-resume (2026-05-16): WAL + snapshot per-tick ----

    def _init_wal_and_snapshot_hooks(self, *, ticks_per_day: int) -> None:
        """Initialize WAL writer + register on_tick_end hook for snapshot writes.

        Both depend on `output_dir`. If output_dir is None, snapshots and WAL
        are disabled (backward-compat for dev mode)."""
        if self._output_dir is None:
            return

        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            WALWriter, snapshot_path, prune_snapshots,
        )

        policy = self._snapshot_policy
        if policy.wal_enabled:
            self._wal_writer = WALWriter(
                output_dir=self._output_dir,
                seed=self._seed,
                fsync_every_ticks=policy.wal_fsync_every_ticks,
            )

        def _on_tick_end_resume_hook(tick_result: Any) -> None:
            # Compute tick_index_global
            day_idx = getattr(tick_result, "day_index", 0)
            tick_idx = getattr(tick_result, "tick_index", 0)
            tick_global = day_idx * ticks_per_day + tick_idx

            # Snapshot at N-tick boundaries (skip tick 0 to avoid duplicate
            # with initial state)
            snap_path = None
            if (
                policy.every_ticks > 0
                and tick_global > 0
                and tick_global % policy.every_ticks == 0
            ):
                snap_path = self._write_snapshot(
                    tick_index_global=tick_global,
                    day_index=day_idx,
                    tick_result=tick_result,
                )
                if snap_path is not None:
                    prune_snapshots(
                        self._output_dir, seed=self._seed,
                        keep=policy.keep_last_k,
                    )

            # WAL append (after snapshot so the WAL row points at the new file)
            if self._wal_writer is not None:
                try:
                    self._wal_writer.append(
                        tick_index=tick_global,
                        day_index=day_idx,
                        simulated_time=getattr(
                            tick_result, "simulated_time", datetime.utcnow(),
                        ) or datetime.utcnow(),
                        commits_succeeded=len([
                            c for c in getattr(tick_result, "commits", [])
                            if getattr(getattr(c, "result", None), "success", False)
                        ]),
                        commits_failed=len([
                            c for c in getattr(tick_result, "commits", [])
                            if not getattr(getattr(c, "result", None), "success", True)
                        ]),
                        encounter_count=len(
                            getattr(tick_result, "encounter_candidates", []) or []
                        ),
                        snapshot_path=snap_path,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "WAL append failed at tick_global=%d: %s",
                        tick_global, exc,
                    )

        self._orchestrator.register_on_tick_end(_on_tick_end_resume_hook)

    def _write_snapshot(
        self,
        *,
        tick_index_global: int,
        day_index: int,
        tick_result: Any,
    ) -> Any:
        """Write a full SimulationCheckpoint snapshot. Returns the Path,
        or None on failure (logged warning, no exception propagated)."""
        if self._output_dir is None:
            return None
        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            SimulationCheckpoint, snapshot_path,
        )

        ledger = getattr(self._orchestrator, "_ledger", None)
        agents = self._collect_agents()

        try:
            snap = SimulationCheckpoint(
                seed=self._seed,
                tick_index=tick_index_global,
                day_index=day_index,
                simulated_time=(
                    getattr(tick_result, "simulated_time", None)
                    or (ledger.current_time if ledger else datetime.utcnow())
                ),
                ledger_state=(
                    ledger.to_snapshot_state() if ledger is not None else {}
                ),
                agent_runtime_states={
                    aid: a.to_snapshot_state() for aid, a in agents.items()
                },
                memory_store_state=(
                    self._memory_service.to_snapshot_state()
                    if self._memory_service is not None else {}
                ),
                attention_service_state=(
                    self._attention_service.to_snapshot_state()
                    if self._attention_service is not None else {}
                ),
                rng_state={},  # Caller-injected RNGs not tracked here; future work
                pending_ops_meta={},
                provider=self._provider_name,
            )
            path = snapshot_path(
                self._output_dir, seed=self._seed,
                tick_index_global=tick_index_global,
            )
            snap.write_atomic(path)
            return path
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "snapshot write failed at tick_global=%d: %s",
                tick_index_global, exc,
            )
            return None

    def _write_final_snapshot_on_graceful_stop(
        self,
        *,
        agents_by_id: dict[str, "AgentRuntime"],
    ) -> None:
        """SIGUSR1 → write a final snapshot regardless of N-tick boundary."""
        if self._output_dir is None:
            return
        # Use orchestrator state to get the most recent tick info
        ledger = getattr(self._orchestrator, "_ledger", None)
        if ledger is None:
            return
        # Best-effort: use ledger's simulated_time + day_index 0 placeholder
        # — the actual tick_index_global would need to come from outside the
        # on_tick_end hook scope. For graceful-stop, we just write at
        # "<current sim time>" with a sentinel tick_index = -1 (post-mortem snap)
        try:
            from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
                SimulationCheckpoint, snapshot_path,
            )
            sim_time = ledger.current_time
            snap = SimulationCheckpoint(
                seed=self._seed,
                tick_index=-1,
                day_index=-1,  # sentinel; real day is encoded in WAL last line
                simulated_time=sim_time,
                ledger_state=ledger.to_snapshot_state(),
                agent_runtime_states={
                    aid: a.to_snapshot_state() for aid, a in agents_by_id.items()
                },
                memory_store_state=(
                    self._memory_service.to_snapshot_state()
                    if self._memory_service is not None else {}
                ),
                attention_service_state=(
                    self._attention_service.to_snapshot_state()
                    if self._attention_service is not None else {}
                ),
                rng_state={},
                pending_ops_meta={},
                provider=self._provider_name,
            )
            # Use a special "final" name so it doesn't collide with N-tick snaps
            path = self._output_dir / f"seed_{self._seed}_tick_final.snapshot.json"
            snap.write_atomic(path)
            logger.info(
                "Graceful-stop final snapshot written to %s", path,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Final snapshot on graceful-stop failed: %s", exc,
            )

    # ---- run-resilience checkpoint helpers ----

    def _write_partial(
        self,
        *,
        day_index: int,
        simulated_date: date,
        per_day: list[DayRunSummary],
        agents_by_id: dict[str, "AgentRuntime"],
    ) -> None:
        """Write checkpoint at the end of `day_index`. Failures log a warning
        but do not interrupt the run."""
        if self._output_dir is None or self._checkpoint_writer is None:
            return
        try:
            self._checkpoint_writer.write_partial(
                output_dir=self._output_dir,
                seed=self._seed,
                day_index=day_index,
                simulated_date=simulated_date,
                run_metrics=self._serialize_per_day(per_day),
                ledger_snapshot=self._serialize_ledger_snapshot(),
                memory_dump=self._serialize_memory_dump(agents_by_id),
                provider=self._provider_name,
            )
        except OSError as exc:
            logger.warning(
                "checkpoint write_partial failed for seed=%d day=%d: %s",
                self._seed, day_index, exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "checkpoint write_partial unexpected failure "
                "for seed=%d day=%d: %s", self._seed, day_index, exc,
            )

    def _write_partial_at_stop(
        self,
        *,
        per_day: list[DayRunSummary],
        agents_by_id: dict[str, "AgentRuntime"],
    ) -> None:
        """SIGUSR1 graceful-stop checkpoint: re-write the most recent
        completed day's partial（partial 内部一致性：不写 in-progress
        day 的部分 tick 数据）。No-op if no day has completed yet."""
        if not per_day:
            return
        last = per_day[-1]
        self._write_partial(
            day_index=last.day_index,
            simulated_date=last.simulated_date,
            per_day=per_day,
            agents_by_id=agents_by_id,
        )

    def _serialize_per_day(
        self, per_day: list[DayRunSummary],
    ) -> dict[str, Any]:
        """Serialize the run-so-far as JSON-safe dict. Used as `run_metrics`
        field in the partial JSON (a thin placeholder; full RunMetrics is
        owned by suite-wiring and will be merged on resume)."""
        return {
            "per_day_summaries": [
                {
                    "day_index": d.day_index,
                    "simulated_date": d.simulated_date.isoformat(),
                    "tick_count": d.tick_count,
                    "commit_succeeded": d.commit_succeeded,
                    "commit_failed": d.commit_failed,
                    "encounter_count": d.encounter_count,
                }
                for d in per_day
            ],
            "total_ticks": sum(d.tick_count for d in per_day),
            "total_encounters": sum(d.encounter_count for d in per_day),
        }

    def _serialize_ledger_snapshot(self) -> dict[str, Any]:
        """Thin ledger snapshot: agent_id → location at this moment.

        Full ledger serialization is out of scope; the suite-wiring layer
        is responsible for capturing whatever it needs on resume."""
        snapshot: dict[str, Any] = {}
        ledger = getattr(self._orchestrator, "_ledger", None)
        if ledger is None:
            return snapshot
        entities = getattr(ledger, "entity_states", None) or getattr(
            ledger, "_entity_states", None,
        )
        if entities is None:
            return snapshot
        try:
            iterator = entities.items() if hasattr(entities, "items") else entities
            for item in iterator:
                try:
                    aid, state = item
                except (TypeError, ValueError):
                    continue
                loc = getattr(state, "location", None) or getattr(
                    state, "current_location", None,
                )
                if loc is not None:
                    snapshot[str(aid)] = str(loc)
        except Exception:  # noqa: BLE001
            return snapshot
        return snapshot

    def _serialize_memory_dump(
        self, agents_by_id: dict[str, "AgentRuntime"],
    ) -> dict[str, Any]:
        """Memory dump placeholder; full memory serialization will be added
        in a follow-up change when MemoryService.dump_state exists."""
        if self._memory_service is None:
            return {}
        dump = getattr(self._memory_service, "dump_state", None)
        if callable(dump):
            try:
                return dict(dump(agents_by_id))
            except Exception:  # noqa: BLE001
                return {}
        return {}


__all__ = [
    "MultiDayRunner",
    "MultiDayResult",
    "MultiDayAggregate",
    "DayRunSummary",
    "RunMode",
]
