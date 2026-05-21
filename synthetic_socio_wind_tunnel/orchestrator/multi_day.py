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
import gc
import json
import logging
import math
import os
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


# enforce-worker-rss-cap (2026-05-19): malloc_zone_pressure_relief helper.
#
# `gc.collect()` only handles Python-level cycles; it does NOT hand
# memory back to the OS. On macOS, pymalloc arenas and dylib-internal
# allocators sit in DefaultMallocZone, which is ~89% fragmented at
# publishable scale (6.1GB of 7.4GB unreclaimable by gc alone).
#
# `malloc_zone_pressure_relief(NULL, 0)` is Apple's hint to libmalloc
# to return free pages to the kernel. Empirically it can reclaim
# 2-4GB of fragmented arena pages after a `gc.collect()` cycle.
#
# Linux equivalent (TODO when project goes cross-platform):
# `ctypes.CDLL("libc.so.6").malloc_trim(0)`.
#
# Failure semantics: SHALL NEVER crash the run. First failure logs a
# WARNING and sets the module-level disable flag; subsequent calls
# return silently. This matches the run-resilience invariant that
# memory-hygiene helpers are best-effort.
_pressure_relief_disabled: bool = False


def _call_malloc_pressure_relief() -> None:
    """Hint libmalloc to return free pages to the OS.

    macOS: calls libc `malloc_zone_pressure_relief(NULL, 0)`.
    Linux: TODO — `malloc_trim(0)`. Currently a silent no-op.
    Other platforms: silent no-op.

    Best-effort; failures fall back silently after one warning.
    """
    import sys

    global _pressure_relief_disabled
    if _pressure_relief_disabled:
        return

    try:
        if sys.platform == "darwin":
            import ctypes
            libc = ctypes.CDLL("libc.dylib")
            # void* malloc_zone_pressure_relief(malloc_zone_t *zone, size_t goal);
            # NULL zone -> all zones; 0 goal -> default behavior
            libc.malloc_zone_pressure_relief(None, 0)
        else:
            # Linux/Windows path not yet implemented; silent no-op
            return
    except Exception as exc:  # noqa: BLE001
        _pressure_relief_disabled = True
        logger.warning(
            "[memory] malloc_zone_pressure_relief failed (%s); "
            "disabling further calls this process. "
            "gc.collect still runs but OS-level page reclaim is off.",
            exc,
        )


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

    # backlog 1.13 第二阶段 (2026-05-19): per-day LLM health visibility
    # 防"沉默灾难"——high fallback% 的 day 在 contest / report 必须可见
    # 否则下次又看似跑完了实则是 fallback 模板数据。
    llm_fallback_pct: float = 0.0
    """rolling fallback rate at day end, 0.0–1.0。LLMHealthTracker snapshot。"""
    llm_total_samples: int = 0
    """rolling window 内 sample count at day end，用于判断 fallback_pct 是否可信
    （n < 50 时 fallback_pct 不稳定，downstream 看 warning 应一起读两个）。"""
    all_keys_open_count: int = 0
    """该 day end 时 LLMHealthTracker 累计的 AllKeysOpenError 次数。"""

    # establish-observability-baselines (2026-05-19): runtime observability
    # 字段——让 publishable run 自带 hot-path 时间序列；不再靠拍脑袋猜
    # RSS / memory store growth / tick latency 分布。所有字段向后兼容
    # default，旧 JSON 缺这些字段时仍可读。详见
    # openspec/specs/runtime-observability/spec.md
    rss_mb: float = 0.0
    """psutil.Process().memory_info().rss / 1024 / 1024 at day_end。"""
    vms_mb: float = 0.0
    """psutil.Process().memory_info().vms / 1024 / 1024 at day_end。"""
    memory_store_event_count: int = 0
    """Σ len(store._events) across all agents at day_end。"""
    dialogue_count: int = 0
    """len(_dialogues) + len(_dialogue_summaries) at day_end。"""
    gc_collections: tuple[int, int, int] = (0, 0, 0)
    """gc.get_count() 三代 counts at day_end。"""
    tick_latency_ms_p50: float = 0.0
    """per-tick wall-clock 分布 p50（毫秒），within this day。"""
    tick_latency_ms_p95: float = 0.0
    """per-tick wall-clock 分布 p95（毫秒），within this day。"""
    tick_latency_ms_max: float = 0.0
    """per-tick wall-clock 最大值（毫秒），within this day。"""

    # enforce-worker-rss-cap (2026-05-19): cold-prune encounter events
    # at day_end to bound `memory_store_state` size. Default grace 2
    # simulated days; env `MEMORY_EVENT_EVICT_GRACE_DAYS` overrides.
    evicted_encounter_count: int = 0
    """该 day_end 触发 cold-prune 删掉的 encounter event 数（across all agents）。"""


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
                    "llm_fallback_pct": d.llm_fallback_pct,
                    "llm_total_samples": d.llm_total_samples,
                    "all_keys_open_count": d.all_keys_open_count,
                    "rss_mb": d.rss_mb,
                    "vms_mb": d.vms_mb,
                    "memory_store_event_count": d.memory_store_event_count,
                    "dialogue_count": d.dialogue_count,
                    "gc_collections": list(d.gc_collections),
                    "tick_latency_ms_p50": d.tick_latency_ms_p50,
                    "tick_latency_ms_p95": d.tick_latency_ms_p95,
                    "tick_latency_ms_max": d.tick_latency_ms_max,
                    "evicted_encounter_count": d.evicted_encounter_count,
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


# ---- persist-per-day-summaries-across-resumes (2026-05-20) helpers ----
#
# Free functions (module-level) so subprocess tests + future audit
# scripts can import without instantiating MultiDayRunner.


def _day_run_summary_to_dict(d: DayRunSummary) -> dict[str, Any]:
    """Serialize a single DayRunSummary to the same schema
    `MultiDayResult.model_dump` uses for per_day_summaries entries.

    Persisted as `seed_<N>_day<D>.summary.json`; read back at resume
    via `_day_run_summary_from_dict`.
    """
    return {
        "day_index": d.day_index,
        "simulated_date": d.simulated_date.isoformat(),
        "tick_count": d.tick_count,
        "commit_succeeded": d.commit_succeeded,
        "commit_failed": d.commit_failed,
        "encounter_count": d.encounter_count,
        "llm_fallback_pct": d.llm_fallback_pct,
        "llm_total_samples": d.llm_total_samples,
        "all_keys_open_count": d.all_keys_open_count,
        "rss_mb": d.rss_mb,
        "vms_mb": d.vms_mb,
        "memory_store_event_count": d.memory_store_event_count,
        "dialogue_count": d.dialogue_count,
        "gc_collections": list(d.gc_collections),
        "tick_latency_ms_p50": d.tick_latency_ms_p50,
        "tick_latency_ms_p95": d.tick_latency_ms_p95,
        "tick_latency_ms_max": d.tick_latency_ms_max,
        "evicted_encounter_count": d.evicted_encounter_count,
        "daily_summary_batch": {
            aid: {
                "agent_id": s.agent_id,
                "date": s.date,
                "summary_text": s.summary_text,
            }
            for aid, s in d.daily_summary_batch.items()
        },
    }


def _day_run_summary_from_dict(raw: dict[str, Any]) -> DayRunSummary:
    """Reconstruct DayRunSummary from a persisted dict (lossy on
    DailySummary.event_tags/event_importance — those are not stored in
    the model_dump schema, but downstream consumers only read the 3
    DailySummary fields kept here)."""
    from synthetic_socio_wind_tunnel.memory.models import DailySummary
    batch = {
        aid: DailySummary(
            agent_id=s["agent_id"],
            date=s["date"],
            summary_text=s["summary_text"],
        )
        for aid, s in raw.get("daily_summary_batch", {}).items()
    }
    return DayRunSummary(
        day_index=int(raw["day_index"]),
        simulated_date=date.fromisoformat(raw["simulated_date"]),
        tick_count=int(raw["tick_count"]),
        commit_succeeded=int(raw["commit_succeeded"]),
        commit_failed=int(raw["commit_failed"]),
        encounter_count=int(raw["encounter_count"]),
        daily_summary_batch=batch,
        llm_fallback_pct=float(raw.get("llm_fallback_pct", 0.0)),
        llm_total_samples=int(raw.get("llm_total_samples", 0)),
        all_keys_open_count=int(raw.get("all_keys_open_count", 0)),
        rss_mb=float(raw.get("rss_mb", 0.0)),
        vms_mb=float(raw.get("vms_mb", 0.0)),
        memory_store_event_count=int(raw.get("memory_store_event_count", 0)),
        dialogue_count=int(raw.get("dialogue_count", 0)),
        gc_collections=tuple(raw.get("gc_collections", (0, 0, 0))),  # type: ignore[arg-type]
        tick_latency_ms_p50=float(raw.get("tick_latency_ms_p50", 0.0)),
        tick_latency_ms_p95=float(raw.get("tick_latency_ms_p95", 0.0)),
        tick_latency_ms_max=float(raw.get("tick_latency_ms_max", 0.0)),
        evicted_encounter_count=int(raw.get("evicted_encounter_count", 0)),
    )


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
        "_tick_metrics_recorder",
        "_dialogue_service",
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
        # establish-observability-baselines (2026-05-19): per-tick
        # latency buffer, reset per day; consumed at day_end.
        "_day_tick_latencies_ms",
        # fix-snapshot-filename-spawn-collision (2026-05-21): PID-based
        # spawn identifier embedded in snapshot filenames.
        "_spawn_id",
        # ledger-anchor-on-resume (2026-05-21): start_date captured at
        # run_multi_day entry, written into every snapshot for drift detect.
        "_start_date_anchor",
    )

    def __init__(
        self,
        *,
        orchestrator: "Orchestrator",
        memory_service: "MemoryService | None" = None,
        attention_service: Any = None,
        tick_metrics_recorder: Any = None,
        dialogue_service: Any = None,
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
        self._tick_metrics_recorder = tick_metrics_recorder
        self._dialogue_service = dialogue_service
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

        # 2026-05-21 R5 (cross-variant-sim-time-anchor): coordinate
        # start_date across variants via suite-level SUITE_ANCHOR.json.
        # Returns the canonical date (anchor's if present, caller's if
        # not). Defensive — typos / stale CLI args won't break alignment.
        canonical_start_date = start_date
        if self._output_dir is not None:
            # output_dir = <suite_dir>/variant_<v>; suite_dir = output_dir.parent
            suite_dir = self._output_dir.parent
            # Variant name is derivable from output_dir.name (e.g.
            # "variant_baseline" → "baseline")
            variant_name = self._output_dir.name
            if variant_name.startswith("variant_"):
                variant_name = variant_name[len("variant_"):]
            try:
                canonical_start_date = (
                    MultiDayRunner._read_or_write_suite_anchor_static(
                        suite_dir=suite_dir,
                        configured_start_date=start_date,
                        configured_num_days=num_days,
                        variant_name=variant_name,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[suite-anchor] check failed (%s); proceeding with "
                    "caller's start_date", exc,
                )

        # 2026-05-21 R4 (ledger-anchor-on-resume): capture the canonical
        # start_date for snapshot writing + drift detection on resume.
        self._start_date_anchor = canonical_start_date

        # 导入 agents 映射给 memory carryover 使用
        agents_by_id = self._collect_agents()

        # tick-level-resume: 若有 restore_from，先把 state 灌回各子系统
        effective_start_day = self._resume_from
        effective_start_tick_global = -1  # -1 = 起始时不存在前驱 tick
        if self._restore_from is not None:
            # 2026-05-21 R2 (auto-backup-snapshot-on-resume): cp existing
            # snapshot files to .snapshot_backup_<ts>/ BEFORE any tick
            # processing so a resume-induced overwrite can't destroy
            # forensic state.
            if self._output_dir is not None:
                self._backup_snapshots_before_resume(self._output_dir)

            # 2026-05-21 R4 (ledger-anchor-on-resume): detect ledger drift
            # vs expected (anchor + day_index*24h + tick_index*5min).
            # Warns only — pure detection, no auto-correction.
            try:
                MultiDayRunner._check_ledger_drift_static(
                    snap=self._restore_from,
                    configured_start_date=start_date,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[ledger-drift] check failed (%s); resume continues",
                    exc,
                )

            snap = self._restore_from
            # 2026-05-21: reject graceful-stop sentinel snaps (day_index=-1)
            # as resume sources — they're post-mortem diagnostic only.
            if snap.day_index < 0:
                raise ValueError(
                    f"restore_from.day_index ({snap.day_index}) is the "
                    f"graceful-stop sentinel — this snap is post-mortem "
                    f"only, NOT a valid resume source. Use the most recent "
                    f"periodic snapshot or per-day partial instead.",
                )
            if snap.day_index >= num_days:
                raise ValueError(
                    f"restore_from.day_index ({snap.day_index}) exceeds "
                    f"num_days ({num_days})",
                )
            # wire-instrumentation-stubs: SNAPSHOT_LOAD_START/DONE桩点
            try:
                from synthetic_socio_wind_tunnel.observability import (
                    get_instrumentation,
                )
                from synthetic_socio_wind_tunnel.observability.instrumentation import (
                    _read_current_rss_mb,
                )
                _inst = get_instrumentation()
                _rss_load_before, _ = _read_current_rss_mb()
                _snap_path_str = (
                    str(getattr(snap, "_source_path", ""))
                    if hasattr(snap, "_source_path") else ""
                )
                _snap_size = 0
                if _snap_path_str:
                    try:
                        _snap_size = os.path.getsize(_snap_path_str)
                    except OSError:
                        _snap_size = 0
                _inst.emit_event(
                    kind="PHASE", phase="SNAPSHOT_LOAD_START",
                    snapshot_path=_snap_path_str,
                    size_bytes=_snap_size,
                )
            except Exception:  # noqa: BLE001
                _inst = None
                _rss_load_before = 0

            import time as _t_snap
            _load_t0 = _t_snap.monotonic()
            # 2026-05-21 RESUME-DETERMINISM D: also restore ConversationService
            # state via MemoryService._conversation (the canonical owner).
            _conv_for_restore = getattr(
                self._memory_service, "_conversation", None,
            ) if self._memory_service is not None else None
            snap.restore_into(
                ledger=getattr(self._orchestrator, "_ledger", None),
                agents=agents_by_id,
                memory_service=self._memory_service,
                attention_service=self._attention_service,
                tick_metrics_recorder=self._tick_metrics_recorder,
                dialogue_service=self._dialogue_service,
                conversation_service=_conv_for_restore,
            )
            try:
                if _inst is not None:
                    _rss_load_after, _ = _read_current_rss_mb()
                    _inst.emit_event(
                        kind="PHASE", phase="SNAPSHOT_LOAD_DONE",
                        duration_sec=_t_snap.monotonic() - _load_t0,
                        rss_before_mb=_rss_load_before,
                        rss_after_mb=_rss_load_after,
                        delta_mb=_rss_load_after - _rss_load_before,
                    )
            except Exception:  # noqa: BLE001
                pass
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

        # persist-per-day-summaries-across-resumes (2026-05-20): hydrate
        # `per_day` from disk-resident `seed_<N>_day<D>.summary.json`
        # files written by prior spawns. Filter strictly to
        # `day_index < effective_start_day` so the day loop never
        # double-appends a day. Closes the thesis-blocking bug where
        # 14-day publishable cells finished via multiple resumes had
        # only the last spawn's days in seed_N.json.
        if self._output_dir is not None and self._checkpoint_writer is not None:
            try:
                _raw_summaries = self._checkpoint_writer.load_day_summaries(
                    output_dir=self._output_dir, seed=self._seed,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[bug-F] load_day_summaries failed (seed=%d): %s",
                    self._seed, exc,
                )
                _raw_summaries = []
            for _raw in _raw_summaries:
                _di = _raw.get("day_index", -1)
                if not isinstance(_di, int) or _di < 0 or _di >= effective_start_day:
                    continue
                try:
                    _hyd = _day_run_summary_from_dict(_raw)
                except (KeyError, ValueError, TypeError) as exc:
                    logger.warning(
                        "[bug-F] skipping malformed day_summary "
                        "day_index=%s: %s", _di, exc,
                    )
                    continue
                per_day.append(_hyd)
                total_ticks += _hyd.tick_count
                total_encounters += _hyd.encounter_count
            if per_day:
                logger.info(
                    "[bug-F] hydrated %d prior-spawn day summaries "
                    "(day_indices=%s); resuming from day_index=%d",
                    len(per_day), [d.day_index for d in per_day],
                    effective_start_day,
                )

        # tick-level-resume: 初始化 WAL writer 与 snapshot 写盘 hook
        ticks_per_day = getattr(self._orchestrator, "_ticks_per_day", 288)
        self._init_wal_and_snapshot_hooks(ticks_per_day=ticks_per_day)

        # backlog 1.7 F + B: periodic gc.collect() + RSS-threshold auto-restart
        self._init_memory_management_hooks(ticks_per_day=ticks_per_day)

        # establish-observability-baselines (2026-05-19): per-tick latency
        # collector — each tick contributes its wall-clock ms to a buffer
        # consumed at day_end for p50/p95/max stats. Skip if env
        # OBSERVABILITY_DISABLE=1 (Layer 4 budget test control).
        self._day_tick_latencies_ms: list[float] = []
        if os.environ.get("OBSERVABILITY_DISABLE", "0") != "1":
            self._init_observability_hooks()

        # 注册 graceful-stop 检查 hook：每 tick 末检查 flag，True 时抛
        # _GracefulStop 中断当天剩余 tick。
        def _check_graceful(tick_result: Any) -> None:  # noqa: ARG001
            if self._graceful_stop_requested:
                raise _GracefulStop()

        self._orchestrator.register_on_tick_end(_check_graceful)

        # wire-instrumentation-stubs: TICK_LOOP_START before first day
        try:
            from synthetic_socio_wind_tunnel.observability import (
                get_instrumentation,
            )
            get_instrumentation().emit_event(
                kind="PHASE", phase="TICK_LOOP_START",
                effective_start_day=effective_start_day,
                num_days=num_days,
            )
        except Exception:  # noqa: BLE001
            pass

        try:
            for day_index in range(effective_start_day, num_days):
                current_date = start_date + timedelta(days=day_index)

                # wire-instrumentation-stubs: DAY_START emit
                try:
                    from synthetic_socio_wind_tunnel.observability import (
                        get_instrumentation as _gi,
                    )
                    _gi().emit_event(
                        kind="PHASE", phase="DAY_START",
                        day_index=day_index,
                        sim_date=str(current_date),
                    )
                except Exception:  # noqa: BLE001
                    pass

                # 2026-05-21 mid-day-resume (1.16): skip on_day_start +
                # _generate_plans_for_day on the first resumed day if we
                # already mid-stream (snap.tick_index_in_day > 0). Why:
                # `apply_day_start` is NOT idempotent (e.g.
                # shared_anchor.apply_day_start inject_feed_item appends
                # NotificationEvents to ledger + consumes RNG per recipient);
                # re-firing on resume would double-inject and diverge from
                # fresh. Plans are also already generated in the source run.
                is_mid_day_resume = (
                    self._restore_from is not None
                    and day_index == effective_start_day
                    and getattr(self._restore_from, "tick_index_in_day", 0) > 0
                )
                if on_day_start is not None and not is_mid_day_resume:
                    on_day_start(current_date, day_index)

                # 内置：若 planner + llm_client 都在，生成次日 plan 并挂到 runtime
                if (
                    self._planner is not None
                    and self._llm_client is not None
                    and not is_mid_day_resume
                ):
                    self._generate_plans_for_day(
                        agents_by_id,
                        current_date=current_date,
                        day_index=day_index,
                    )

                # 一日 tick 循环 — 可能被 _GracefulStop 中断
                # 2026-05-21 mid-day-resume (closes backlog 1.16):
                # 第一个 resumed day 从 snap.tick_index_in_day + 1 开始；
                # 后续 day 都从 0 开始（fresh-day semantics）。
                day_start_tick = 0
                if (
                    self._restore_from is not None
                    and day_index == effective_start_day
                    and effective_start_tick_global >= 0
                ):
                    snap_tick_in_day = getattr(
                        self._restore_from, "tick_index_in_day", 0,
                    )
                    # If snap completed the last tick of its day, the
                    # next "fresh" tick is on the NEXT day — but the
                    # outer day loop already iterates day_index ranges,
                    # so we just skip this day entirely by setting
                    # day_start_tick = ticks_per_day.
                    day_start_tick = int(snap_tick_in_day) + 1
                try:
                    day_summary = self._orchestrator.run(
                        day_index=day_index,
                        simulated_date=current_date,
                        start_tick=day_start_tick,
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

                # backlog 1.13 第二阶段: snapshot LLM health at day_end
                # so downstream report can flag high-fallback days.
                from synthetic_socio_wind_tunnel.run_resilience.llm_health import (
                    get_tracker,
                )
                _tracker = get_tracker()
                _fb_rate, _n_samples = _tracker.rolling_rate()
                _aks_open = _tracker.all_keys_open_count()

                # establish-observability-baselines (2026-05-19): runtime
                # observability snapshot at day_end. Low overhead (~1 ms /
                # day total). Failures fallback to defaults — see Layer 6
                # fault injection tests.
                _obs = self._collect_day_end_observability(
                    agents_by_id=agents_by_id,
                    day_tick_latencies_ms=getattr(
                        self, "_day_tick_latencies_ms", [],
                    ),
                )

                day_run = DayRunSummary(
                    day_index=day_index,
                    simulated_date=current_date,
                    tick_count=day_summary.total_ticks,
                    commit_succeeded=day_summary.total_commits_succeeded,
                    commit_failed=day_summary.total_commits_failed,
                    encounter_count=day_summary.total_encounters,
                    daily_summary_batch=batch,
                    llm_fallback_pct=_fb_rate,
                    llm_total_samples=_n_samples,
                    all_keys_open_count=_aks_open,
                    **_obs,
                )
                # Reset per-tick latency buffer for next day
                self._day_tick_latencies_ms = []
                per_day.append(day_run)

                # Per-day checkpoint write — BEFORE on_day_end hook so external
                # consumers see a consistent partial on disk
                self._write_partial(
                    day_index=day_index,
                    simulated_date=current_date,
                    per_day=per_day,
                    agents_by_id=agents_by_id,
                )

                # harden-worker-resilience: DialogueService rolling
                # cleanup. Demote dialogues that started ≥ 2 simulated
                # days ago to compact summaries (drops messages list)
                # so 14-day workers don't bleed 100-500 MB.
                # fix-dialogue-eviction-tick-semantic (2026-05-20):
                # changed from `before_tick = cutoff_tick * 288` (global)
                # to `before_day_index = max(0, day - grace)`. Previous
                # version compared ev.ended_tick (per-day) against global
                # cutoff → always True → all ended dialogues evicted
                # immediately, no grace.
                if self._dialogue_service is not None:
                    grace_days = int(
                        os.environ.get("DIALOGUE_EVICT_GRACE_DAYS", "2")
                    )
                    before_day_index = max(0, day_index - grace_days)
                    try:
                        self._dialogue_service.evict_old_dialogues(
                            before_day_index=before_day_index,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "DialogueService.evict_old_dialogues failed "
                            "at day_index=%d: %s", day_index, exc,
                        )

                # enforce-worker-rss-cap (2026-05-19): cold-prune
                # encounter events from memory_store. Eviction keeps
                # RSS bounded for the 10GB hard cap.
                # fix-encounter-eviction-tick-semantic (2026-05-20):
                # changed from `before_tick = cutoff*288` to
                # `before_day_index = max(0, day_index - grace)` —
                # the old version compared ev.tick (per-day 0-287)
                # against a global cutoff so all encounter events
                # were always evicted. Now compares ev.day_index
                # against before_day_index, matching caller intent.
                evicted_encounter_count = 0
                if self._memory_service is not None:
                    encounter_grace = int(
                        os.environ.get("MEMORY_EVENT_EVICT_GRACE_DAYS", "2")
                    )
                    before_day_index = max(0, day_index - encounter_grace)
                    if before_day_index > 0:
                        try:
                            evicted_encounter_count = (
                                self._memory_service
                                .evict_cold_encounter_events_across_agents(
                                    before_day_index=before_day_index,
                                )
                            )
                            if evicted_encounter_count > 0:
                                logger.info(
                                    "[memory-evict] day=%d "
                                    "before_day_index=%d evicted %d "
                                    "encounter events",
                                    day_index, before_day_index,
                                    evicted_encounter_count,
                                )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "evict_cold_encounter_events_across_agents "
                                "failed at day_index=%d: %s",
                                day_index, exc,
                            )
                # backlog 1.7 A+ (2026-05-22): optional action eviction.
                # Opt-in via env ACTION_EVICT_ENABLED=true. Reuses the
                # same GRACE window as encounters (or ACTION_EVICT_GRACE_DAYS
                # override). Drops day < grace action events to bound the
                # second-largest event kind post-encounter-dedup.
                if (
                    self._memory_service is not None
                    and os.environ.get(
                        "ACTION_EVICT_ENABLED", "false",
                    ).strip().lower() in ("1", "true", "yes")
                ):
                    try:
                        action_grace = int(os.environ.get(
                            "ACTION_EVICT_GRACE_DAYS",
                            os.environ.get(
                                "MEMORY_EVENT_EVICT_GRACE_DAYS", "2",
                            ),
                        ))
                    except ValueError:
                        action_grace = 2
                    action_before = max(0, day_index - action_grace)
                    if action_before > 0:
                        try:
                            evicted_action = (
                                self._memory_service
                                .evict_cold_action_events_across_agents(
                                    before_day_index=action_before,
                                )
                            )
                            if evicted_action > 0:
                                logger.info(
                                    "[memory-evict] day=%d "
                                    "before_day_index=%d evicted %d "
                                    "action events",
                                    day_index, action_before, evicted_action,
                                )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "evict_cold_action_events_across_agents "
                                "failed at day_index=%d: %s",
                                day_index, exc,
                            )
                # Patch the most-recent DayRunSummary with eviction count
                # (per_day_summaries[-1] was just appended above)
                if per_day:
                    from dataclasses import replace as _dc_replace
                    per_day[-1] = _dc_replace(
                        per_day[-1],
                        evicted_encounter_count=evicted_encounter_count,
                    )

                # persist-per-day-summaries-across-resumes (2026-05-20):
                # write this day's enriched summary to disk so the next
                # resume hydrates it instead of dropping it on the floor.
                # Independent of partial / snapshot — survives
                # cleanup_partials on cell completion.
                if (
                    self._output_dir is not None
                    and self._checkpoint_writer is not None
                    and per_day
                ):
                    try:
                        self._checkpoint_writer.write_day_summary(
                            day_index=day_index,
                            summary_dict=_day_run_summary_to_dict(per_day[-1]),
                            output_dir=self._output_dir,
                            seed=self._seed,
                        )
                    except OSError as exc:
                        logger.warning(
                            "[bug-F] write_day_summary failed for "
                            "day_index=%d: %s", day_index, exc,
                        )

                # on_day_end: 外部 hook 可读 batch 做 metrics 采集 / phase 转
                if on_day_end is not None:
                    on_day_end(current_date, day_index, batch)

                # wire-instrumentation-stubs: DAY_END emit
                try:
                    from synthetic_socio_wind_tunnel.observability import (
                        get_instrumentation as _gi_end,
                    )
                    _gi_end().emit_event(
                        kind="PHASE", phase="DAY_END",
                        day_index=day_index,
                        sim_date=str(current_date),
                        evicted_encounter_count=evicted_encounter_count,
                    )
                except Exception:  # noqa: BLE001
                    pass
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

        # harden-worker-resilience: graceful_stop 在 setup-phase（per_day=[]，
        # 没完成过任何 day）时写哨兵文件让外部 audit / resume_publishable
        # 区分"setup 期被中断"vs"已跑了几天被中断"。
        aborted_in_setup = (
            self._graceful_stop_requested and not per_day
        )
        if aborted_in_setup and self._output_dir is not None:
            self._write_aborted_in_setup_sentinel()

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
                "aborted_in_setup": aborted_in_setup,
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
            # 2026-05-21 backlog 1.18: wrap generate_daily_plan in
            # asyncio.wait_for so a single hung LLM call doesn't
            # deadlock the asyncio.gather over 500 protag plans.
            # Violation of CLAUDE.md 1.9 "all-direct-LLM-call SHALL
            # be wrapped in wait_for" — close it now.
            try:
                plan = await asyncio.wait_for(
                    self._planner.generate_daily_plan(
                        agent.profile,
                        date=current_date.isoformat(),
                        carryover=carryover,
                    ),
                    timeout=90.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "plan gen timeout (90s) for agent=%s day=%d; "
                    "falling back to template plan",
                    agent.profile.agent_id, day_index,
                )
                # Fallback: leave agent.plan unchanged (carry the previous
                # plan or None). The agent will operate from
                # scripted_plan defaults — acceptable degradation.
                return
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

            # Capability 1.13 (2026-05-19): check rolling fallback-rate
            # budget. Raises FallbackBudgetExceeded after N consecutive
            # ticks over threshold — caught at run_multi_day level to
            # write partial + propagate non-zero exit.
            from synthetic_socio_wind_tunnel.run_resilience.llm_health import (
                get_tracker,
            )
            get_tracker().check_budget()

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

    def _init_memory_management_hooks(self, *, ticks_per_day: int) -> None:
        """Backlog 1.7 F + B: periodic gc.collect + RSS-threshold auto-restart.

        F (gc.collect): every N ticks (default 200) force-collect garbage
        cycles. Python's reference counting alone doesn't break cycles, and
        long-running workers accumulate 100-300 MB of uncollected garbage.
        Zero-risk hint to the runtime; env: `GC_EVERY_N_TICKS` (0 = off).

        B (RSS-threshold auto-restart): every M ticks (default 50) check
        self RSS. If above threshold (default 2.5 GB; env: `RSS_RESTART_MB`),
        set `_graceful_stop_requested = True` — the existing graceful-stop
        path then writes per-day partials and exits cleanly. Outer
        `resume_publishable.py` / LaunchAgent re-spawn replaces the bloated
        worker with a fresh one resuming from snapshot. Net effect: each
        worker's RSS oscillates around the threshold instead of climbing
        unbounded. Env: `RSS_RESTART_MB` (0 = off).

        See CLAUDE.md `snapshot-resume-ram-peak` and
        `sigusr1-graceful-stop-corruption` invariants — both are
        prerequisites for B to be safe to enable. As of 2026-05-19 the
        latter is fixed in `run_variant_suite.py`, so B is now safe to
        enable.
        """
        gc_every = int(os.environ.get("GC_EVERY_N_TICKS", "200"))
        rss_threshold_mb = int(os.environ.get("RSS_RESTART_MB", "0"))
        rss_check_every = int(os.environ.get("RSS_CHECK_EVERY_N_TICKS", "50"))
        # wire-instrumentation-stubs (2026-05-20): also enable hook
        # registration when memstat sampling is on (was previously
        # gated only on gc/RSS). Default 12 ticks matches the
        # observability latency hook cadence.
        memstat_every = int(os.environ.get(
            "INSTRUMENTATION_SAMPLE_EVERY_N_TICKS", "12",
        ))

        if gc_every <= 0 and rss_threshold_mb <= 0 and memstat_every <= 0:
            return  # all three disabled

        # 2026-05-20 comprehensive-runtime-instrumentation: fix critical
        # bug where `_self_rss_mb` used `resource.getrusage().ru_maxrss`
        # (LIFETIME PEAK, not current). After a single 35GB snapshot
        # deserialize, ru_maxrss stays at 35GB forever, making the RSS
        # cap trip permanently. Now uses psutil current RSS first;
        # ru_maxrss fallback only when psutil unavailable.
        def _current_rss_mb() -> int | None:
            try:
                import psutil
                return psutil.Process().memory_info().rss // (1024 * 1024)
            except ImportError:
                logger.warning(
                    "[memory] psutil unavailable; RSS cap falling back "
                    "to ru_maxrss (LIFETIME PEAK) — may misfire after "
                    "one high-RSS event",
                )
            except (psutil.Error if "psutil" in dir() else Exception):
                pass
            # Fallback path
            try:
                import resource
                ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                import sys
                if sys.platform == "darwin":
                    return ru // (1024 * 1024)
                return ru // 1024
            except (ImportError, OSError):
                return None

        # Backward-compat alias for any pre-fix call sites (none remain
        # in this module but external monkey-patches might reference)
        _self_rss_mb = _current_rss_mb

        def _on_tick_end_memory(tick_result: Any) -> None:
            day_idx = getattr(tick_result, "day_index", 0)
            tick_idx = getattr(tick_result, "tick_index", 0)
            tick_global = day_idx * ticks_per_day + tick_idx
            if tick_global <= 0:
                return

            # wire-instrumentation-stubs (2026-05-20): periodic memstat
            # sample at the documented cadence. Best-effort — failure
            # SHALL NOT crash the worker.
            if (
                memstat_every > 0
                and tick_global % memstat_every == 0
            ):
                try:
                    from synthetic_socio_wind_tunnel.observability import (
                        get_instrumentation,
                    )
                    try:
                        from synthetic_socio_wind_tunnel.run_resilience.llm_health import (
                            get_tracker as _get_tracker,
                        )
                        _tracker = _get_tracker()
                    except Exception:  # noqa: BLE001
                        _tracker = None
                    _sim_iso = None
                    _sim = getattr(tick_result, "simulated_time", None)
                    if _sim is not None and hasattr(_sim, "isoformat"):
                        try:
                            _sim_iso = _sim.isoformat()
                        except Exception:  # noqa: BLE001
                            _sim_iso = None
                    get_instrumentation().sample_metrics(
                        tick_global=tick_global,
                        day_index=day_idx,
                        tick_in_day=tick_idx,
                        memory_service=self._memory_service,
                        dialogue_service=self._dialogue_service,
                        llm_tracker=_tracker,
                        sim_time_iso=_sim_iso,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "[memstat] sample_metrics failed: %s", exc,
                    )

            if gc_every > 0 and tick_global % gc_every == 0:
                freed = gc.collect()
                # enforce-worker-rss-cap: hand free pages back to the OS
                # after cycle collection — gc.collect alone leaves
                # pymalloc arenas pinned (89% fragmentation on macOS
                # at publishable scale).
                _call_malloc_pressure_relief()
                rss_after = _self_rss_mb()
                logger.info(
                    "[gc] tick_global=%d freed=%d cycles rss=%sMB",
                    tick_global, freed,
                    rss_after if rss_after is not None else "?",
                )

            if (
                rss_threshold_mb > 0
                and tick_global % rss_check_every == 0
                and not self._graceful_stop_requested
            ):
                rss = _self_rss_mb()
                if rss is not None and rss > rss_threshold_mb:
                    logger.warning(
                        "[memory] RSS %dMB > threshold %dMB at "
                        "tick_global=%d — requesting graceful stop "
                        "(backlog 1.7 B auto-restart); outer launcher "
                        "should resume from snapshot",
                        rss, rss_threshold_mb, tick_global,
                    )
                    self._graceful_stop_requested = True

        self._orchestrator.register_on_tick_end(_on_tick_end_memory)

    def _init_observability_hooks(self) -> None:
        """establish-observability-baselines: register a per-tick hook
        that records tick wall-clock latency into `_day_tick_latencies_ms`.

        Samples every Nth tick (default 12, env
        `OBSERVABILITY_LATENCY_SAMPLE_EVERY_N_TICKS`). 24 samples/day is
        sufficient for p50/p95/max estimation while keeping overhead
        < 5% at dev scale (per-tick sampling at 50 agent gave 37%
        overhead — sample-every-N cuts it 12×).

        Skipped entirely when env `OBSERVABILITY_DISABLE=1`.
        """
        import time as _t
        sample_every_n = int(
            os.environ.get("OBSERVABILITY_LATENCY_SAMPLE_EVERY_N_TICKS", "12"),
        )
        state = {"last": _t.perf_counter(), "tick_count": 0}

        def _on_tick_end_latency(tick_result: Any) -> None:  # noqa: ARG001
            state["tick_count"] += 1
            if state["tick_count"] % sample_every_n != 0:
                return
            now = _t.perf_counter()
            delta_ms = (now - state["last"]) * 1000.0 / sample_every_n
            state["last"] = now
            if len(self._day_tick_latencies_ms) < 100:
                self._day_tick_latencies_ms.append(delta_ms)

        self._orchestrator.register_on_tick_end(_on_tick_end_latency)

    def _collect_day_end_observability(
        self,
        *,
        agents_by_id: dict[str, "AgentRuntime"],
        day_tick_latencies_ms: list[float],
    ) -> dict[str, Any]:
        """Snapshot runtime observability at day_end for DayRunSummary.

        ALL failures fallback to safe defaults — never crash the run.
        Each metric is wrapped independently so one failing metric
        doesn't poison the others.

        Spec: openspec/specs/runtime-observability/spec.md Requirement
        "MultiDayRunner 必须在 day_end hook 内部 instrument".
        """
        out: dict[str, Any] = {
            "rss_mb": 0.0,
            "vms_mb": 0.0,
            "memory_store_event_count": 0,
            "dialogue_count": 0,
            "gc_collections": (0, 0, 0),
            "tick_latency_ms_p50": 0.0,
            "tick_latency_ms_p95": 0.0,
            "tick_latency_ms_max": 0.0,
        }

        # RSS / VMS via psutil
        try:
            import psutil  # late import: optional dev dep
            proc = psutil.Process()
            mem = proc.memory_info()
            out["rss_mb"] = round(mem.rss / 1024 / 1024, 2)
            out["vms_mb"] = round(mem.vms / 1024 / 1024, 2)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[observability] psutil memory_info failed: %s "
                "(fallback rss_mb=0, vms_mb=0)", exc,
            )

        # gc generation counts
        try:
            out["gc_collections"] = tuple(gc.get_count())  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[observability] gc.get_count failed: %s", exc)

        # memory_store event count
        try:
            if self._memory_service is not None:
                total = 0
                stores = getattr(self._memory_service, "_stores", {}) or {}
                for store in stores.values():
                    events = getattr(store, "_events", None)
                    if events is not None:
                        total += len(events)
                out["memory_store_event_count"] = total
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[observability] memory_store_event_count failed: %s", exc,
            )

        # dialogue count
        try:
            if self._dialogue_service is not None:
                live = len(getattr(self._dialogue_service, "_dialogues", {}) or {})
                summaries = len(
                    getattr(self._dialogue_service, "_dialogue_summaries", {}) or {}
                )
                out["dialogue_count"] = live + summaries
        except Exception as exc:  # noqa: BLE001
            logger.warning("[observability] dialogue_count failed: %s", exc)

        # tick latency p50/p95/max
        if day_tick_latencies_ms:
            try:
                import statistics
                # statistics.quantiles needs n >= 2
                sorted_lats = sorted(day_tick_latencies_ms)
                n = len(sorted_lats)
                if n >= 2:
                    quants = statistics.quantiles(
                        sorted_lats, n=100, method="inclusive",
                    )
                    out["tick_latency_ms_p50"] = round(quants[49], 3)
                    out["tick_latency_ms_p95"] = round(quants[94], 3)
                else:
                    out["tick_latency_ms_p50"] = round(sorted_lats[0], 3)
                    out["tick_latency_ms_p95"] = round(sorted_lats[0], 3)
                out["tick_latency_ms_max"] = round(sorted_lats[-1], 3)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[observability] tick_latency quantiles failed: %s", exc,
                )

        return out

    @staticmethod
    def _read_or_write_suite_anchor_static(
        *,
        suite_dir: Path,
        configured_start_date: date,
        configured_num_days: int,
        variant_name: str,
    ) -> date:
        """R5 (2026-05-21 cross-variant-sim-time-anchor).

        Suite-level coordination: first variant writes
        `<suite_dir>/SUITE_ANCHOR.json` with canonical start_date.
        Subsequent variants verify match. Returns the canonical date
        (anchor's value if present + parseable; caller's value if
        absent or corrupt).

        - file absent → write + return caller's date
        - file present + parseable + matches → silent return anchor's date
        - file present + parseable + mismatch → ERROR + return anchor's
          date (defensive: prevent typo from breaking alignment)
        - file present + corrupt → WARNING + return caller's date (no
          overwrite of corrupt file — forensics)

        Static helper so tests can exercise without instantiating
        MultiDayRunner.
        """
        import json as _json_anchor
        anchor_path = suite_dir / "SUITE_ANCHOR.json"

        if not anchor_path.exists():
            # First variant — write the anchor
            try:
                suite_dir.mkdir(parents=True, exist_ok=True)
                payload = {
                    "start_date_iso": configured_start_date.isoformat(),
                    "num_days": configured_num_days,
                    "created_at": datetime.utcnow().isoformat(),
                    "created_by_variant": variant_name,
                }
                anchor_path.write_text(
                    _json_anchor.dumps(payload, indent=2),
                    encoding="utf-8",
                )
                logger.info(
                    "[suite-anchor] wrote anchor at %s (start_date=%s, "
                    "num_days=%d, variant=%s)",
                    anchor_path, configured_start_date,
                    configured_num_days, variant_name,
                )
            except OSError as exc:
                logger.warning(
                    "[suite-anchor] write failed (%s); proceeding with "
                    "caller's start_date — cross-variant alignment NOT "
                    "guaranteed",
                    exc,
                )
            return configured_start_date

        # Anchor exists — try to parse
        try:
            payload = _json_anchor.loads(
                anchor_path.read_text(encoding="utf-8")
            )
            anchor_date_iso = payload["start_date_iso"]
            anchor_date = date.fromisoformat(anchor_date_iso)
        except (OSError, _json_anchor.JSONDecodeError, KeyError,
                ValueError, TypeError) as exc:
            logger.warning(
                "[suite-anchor] anchor file %s is corrupt or "
                "unparseable (%s); proceeding with caller's start_date — "
                "leaving corrupt file in place for forensics",
                anchor_path, exc,
            )
            return configured_start_date

        if anchor_date != configured_start_date:
            logger.error(
                "[suite-anchor] MISMATCH: anchor says start_date=%s "
                "(created by variant=%s), but %s was called with "
                "start_date=%s. Defensive override: using anchor's value. "
                "Cross-variant alignment preserved despite operator typo / "
                "stale CLI arg.",
                anchor_date,
                payload.get("created_by_variant", "?"),
                variant_name, configured_start_date,
            )
        return anchor_date

    @staticmethod
    def _check_ledger_drift_static(
        *, snap: Any, configured_start_date: date,
    ) -> float | None:
        """R4 (2026-05-21 ledger-anchor-on-resume).

        Compare snap's stored ledger.current_time against the expected
        value computed from (start_date_anchor + day_index*24h +
        tick_index*5min). If drift > 1 hour, log a WARNING.

        Returns the absolute drift in hours, or None if check was
        skipped (legacy snapshot without anchor / malformed data).
        Pure detection — does NOT auto-correct.

        Static so tests can invoke without instantiating MultiDayRunner.
        """
        anchor_iso = getattr(snap, "start_date_anchor_iso", None)
        if not anchor_iso:
            # Legacy / no anchor → skip drift check
            return None
        try:
            anchor_date = date.fromisoformat(anchor_iso)
        except (ValueError, TypeError):
            logger.warning(
                "[ledger-drift] snapshot has malformed start_date_anchor_iso=%r; "
                "skipping drift check",
                anchor_iso,
            )
            return None

        if anchor_date != configured_start_date:
            logger.warning(
                "[ledger-drift] snapshot anchor (%s) != current run "
                "start_date (%s) — variants may have been spawned with "
                "different start_date arguments",
                anchor_date, configured_start_date,
            )

        # Compute expected ledger.current_time.
        #
        # 2026-05-21 (C: drift formula fix): the prior formula
        # `expected = anchor + day*1d + tick*5min` used snap.tick_index
        # (which is tick_GLOBAL = day*ticks_per_day + tick_in_day) as if
        # it were tick_in_day, producing massively inflated `expected`
        # values (off by `day_idx * 24h`). Causes false-positive
        # drift warnings on every cross-variant resume monitoring.
        #
        # Correct: snap fires AFTER tick (day_idx, tick_in_day)
        # completes, so:
        #   expected_ledger_time = anchor + day_idx*1d + (tick_in_day+1)*5min
        #
        # Always derive tick_in_day from tick_global (= snap.tick_index)
        # because the explicit `tick_index_in_day` field defaults to 0
        # on legacy snaps that pre-date the field. Derivation works for
        # both old and new snaps:
        #     tick_in_day = tick_global - day_idx * ticks_per_day
        from datetime import timedelta as _td
        day_idx = getattr(snap, "day_index", 0)
        tick_global = getattr(snap, "tick_index", 0)
        tick_in_day = max(0, tick_global - day_idx * 288)
        expected = (
            datetime.combine(anchor_date, datetime.min.time())
            + _td(days=day_idx, minutes=(tick_in_day + 1) * 5)
        )

        # Read actual ledger time from snap.ledger_state.current_time
        # (str ISO) or fall back to snap.simulated_time
        ledger_state = getattr(snap, "ledger_state", {}) or {}
        actual_iso = ledger_state.get("current_time")
        if not actual_iso:
            actual = getattr(snap, "simulated_time", None)
            if actual is None:
                return None
        else:
            try:
                actual = datetime.fromisoformat(str(actual_iso))
            except (ValueError, TypeError):
                logger.warning(
                    "[ledger-drift] malformed ledger.current_time=%r; "
                    "skipping drift check",
                    actual_iso,
                )
                return None

        drift = actual - expected
        drift_hours = abs(drift.total_seconds()) / 3600.0
        if drift_hours > 1.0:
            logger.warning(
                "[ledger-drift] resume ledger.current_time drift detected: "
                "expected %s (anchor=%s + day=%d + (tick_in_day=%d + 1)*5min), "
                "actual %s, drift=%.1f hours. "
                "Cross-variant contest comparison may be confounded by "
                "calendar offset.",
                expected, anchor_date, day_idx, tick_in_day, actual, drift_hours,
            )
        return drift_hours

    def _backup_snapshots_before_resume(self, output_dir: Path) -> bool:
        """R2 (2026-05-21 auto-backup-snapshot-on-resume).

        On resume, cp all existing `seed_<N>*.snapshot.json` files to
        a subdirectory `.snapshot_backup_<YYYYMMDD_HHMMSS>/` BEFORE
        the tick loop fires any new snapshot write.

        Best-effort: failures log a warning but don't abort the resume.
        Env `RESILIENCE_SKIP_RESUME_BACKUP=1` disables.
        Returns True if backup succeeded (or had nothing to backup);
        False if attempted but failed.
        """
        import os as _os_bk
        import shutil as _shutil_bk
        from datetime import datetime as _dt_bk

        if _os_bk.environ.get("RESILIENCE_SKIP_RESUME_BACKUP") == "1":
            return True

        try:
            # Find existing snapshots (both legacy and PID-prefixed formats)
            snaps = list(output_dir.glob(f"seed_{self._seed}_*.snapshot.json"))
            if not snaps:
                return True  # nothing to backup

            ts = _dt_bk.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = output_dir / f".snapshot_backup_{ts}"
            backup_dir.mkdir(parents=True, exist_ok=True)

            for snap_path in snaps:
                try:
                    _shutil_bk.copy2(snap_path, backup_dir / snap_path.name)
                except OSError as cp_exc:
                    logger.warning(
                        "[resume-backup] copy of %s failed: %s",
                        snap_path.name, cp_exc,
                    )
                    # Continue — best-effort. One failed copy doesn't
                    # abort the whole resume.
            logger.info(
                "[resume-backup] backed up %d snapshot files to %s",
                len(snaps), backup_dir,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[resume-backup] failed (%s); resume continues without backup",
                exc,
            )
            return False

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

        # prune-before-snapshot-write (2026-05-20): cold-prune encounter
        # events BEFORE serializing memory_store_state. snapshot file
        # gets bounded by `grace_days` window, no longer carries 6M+
        # historical encounter events (93.5% of 6GB file). Next resume
        # peak RAM drops 30-35GB → 3-6GB.
        evicted_before_write = 0
        prune_enabled = os.environ.get(
            "SNAPSHOT_PRUNE_BEFORE_WRITE", "true",
        ).strip().lower() not in ("0", "false", "no")
        if prune_enabled and self._memory_service is not None:
            try:
                grace_days = int(os.environ.get(
                    "MEMORY_EVENT_EVICT_GRACE_DAYS", "2",
                ))
            except ValueError:
                grace_days = 2
            # fix-encounter-eviction-tick-semantic (2026-05-20):
            # changed from cutoff_tick (global) to before_day_index.
            # See day_end eviction site for full rationale.
            before_day_index = max(0, day_index - grace_days)
            if before_day_index > 0:
                try:
                    evicted_before_write = (
                        self._memory_service
                        .evict_cold_encounter_events_across_agents(
                            before_day_index=before_day_index,
                        )
                    )
                    if evicted_before_write > 0:
                        logger.info(
                            "[snapshot] pre-write prune evicted %d "
                            "encounter events (before_day_index=%d, "
                            "day_index=%d, grace=%d)",
                            evicted_before_write, before_day_index,
                            day_index, grace_days,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[snapshot] pre-write evict failed at "
                        "tick_global=%d: %s — snapshot will still "
                        "write but may be larger than ideal",
                        tick_index_global, exc,
                    )

            # backlog 1.7 A+ (2026-05-22): action eviction at snapshot
            # pre-write. Same opt-in env as the day_end hook. Combined
            # with encounter dedup, this is what lets 4-worker
            # publishable runs fit in 48GB RAM.
            if os.environ.get(
                "ACTION_EVICT_ENABLED", "false",
            ).strip().lower() in ("1", "true", "yes"):
                try:
                    action_grace = int(os.environ.get(
                        "ACTION_EVICT_GRACE_DAYS",
                        os.environ.get("MEMORY_EVENT_EVICT_GRACE_DAYS", "2"),
                    ))
                except ValueError:
                    action_grace = 2
                action_before = max(0, day_index - action_grace)
                if action_before > 0:
                    try:
                        evicted_actions = (
                            self._memory_service
                            .evict_cold_action_events_across_agents(
                                before_day_index=action_before,
                            )
                        )
                        if evicted_actions > 0:
                            logger.info(
                                "[snapshot] pre-write evicted %d action "
                                "events (before_day_index=%d, grace=%d)",
                                evicted_actions, action_before, action_grace,
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "[snapshot] pre-write action evict failed: "
                            "%s — snapshot will write but bigger",
                            exc,
                        )

        ledger = getattr(self._orchestrator, "_ledger", None)
        agents = self._collect_agents()

        # 2026-05-21 mid-day-resume (closes backlog 1.16): compute
        # tick_in_day from tick_result so the snap encodes "which
        # tick within day_index just finished". MultiDayRunner on
        # resume uses snap.tick_index_in_day + 1 as Orchestrator.run
        # start_tick, avoiding re-execution of the boundary tick.
        ticks_per_day_for_snap = getattr(
            self._orchestrator, "_ticks_per_day", 288,
        )
        # tick_result.tick_index is the in-day tick that just ran;
        # day_index is the day it belongs to. We can also derive via
        # tick_index_global % ticks_per_day, but using tick_result is
        # authoritative (no off-by-one risk).
        tick_in_day_at_snap = int(
            getattr(tick_result, "tick_index", 0)
        )
        # Defensive: clamp to [0, ticks_per_day - 1]
        if tick_in_day_at_snap < 0:
            tick_in_day_at_snap = 0
        if tick_in_day_at_snap >= ticks_per_day_for_snap:
            tick_in_day_at_snap = ticks_per_day_for_snap - 1

        try:
            snap = SimulationCheckpoint(
                seed=self._seed,
                tick_index=tick_index_global,
                day_index=day_index,
                tick_index_in_day=tick_in_day_at_snap,
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
                tick_metrics_recorder_state=(
                    self._tick_metrics_recorder.to_snapshot_state()
                    if self._tick_metrics_recorder is not None else {}
                ),
                dialogue_service_state=(
                    self._dialogue_service.to_snapshot_state()
                    if self._dialogue_service is not None else {}
                ),
                # 2026-05-21 RESUME-DETERMINISM D: capture ConversationService
                # state via MemoryService._conversation. Without this the
                # P(share) probabilistic gate diverges from fresh after resume.
                conversation_service_state=(
                    getattr(self._memory_service, "_conversation").to_snapshot_state()
                    if (
                        self._memory_service is not None
                        and getattr(self._memory_service, "_conversation", None)
                        is not None
                    )
                    else {}
                ),
                rng_state={},  # Caller-injected RNGs not tracked here; future work
                pending_ops_meta={},
                provider=self._provider_name,
                # 2026-05-21 R4 (ledger-anchor-on-resume): preserve the
                # canonical start_date so future resume can detect
                # ledger.current_time drift.
                start_date_anchor_iso=(
                    self._start_date_anchor.isoformat()
                    if getattr(self, "_start_date_anchor", None) is not None
                    else None
                ),
            )
            # 2026-05-21 R1 (fix-snapshot-filename-spawn-collision):
            # include process PID in snapshot filename so respawn doesn't
            # overwrite earlier spawn's snapshots at colliding internal
            # tick numbers. PID is cached on first call to avoid
            # repeated os.getpid() syscalls.
            import os as _os_snap
            spawn_id = getattr(self, "_spawn_id", None) or _os_snap.getpid()
            self._spawn_id = spawn_id  # type: ignore[assignment]
            path = snapshot_path(
                self._output_dir, seed=self._seed,
                tick_index_global=tick_index_global,
                spawn_id=spawn_id,
            )
            # comprehensive-runtime-instrumentation: capture RSS before
            # write to compute peak during; prune-before-snapshot-write:
            # thread evicted count into the event.
            try:
                from synthetic_socio_wind_tunnel.observability import (
                    get_instrumentation,
                )
                from synthetic_socio_wind_tunnel.observability.instrumentation import (
                    _read_current_rss_mb,
                )
                _rss_before, _ = _read_current_rss_mb()
            except Exception:  # noqa: BLE001
                get_instrumentation = None  # type: ignore[assignment]
                _read_current_rss_mb = None  # type: ignore[assignment]
                _rss_before = 0
            import time as _t
            _t0 = _t.monotonic()

            snap.write_atomic(path)

            try:
                if get_instrumentation is not None and _read_current_rss_mb is not None:
                    _rss_after, _ = _read_current_rss_mb()
                    get_instrumentation().emit_snapshot_write(
                        tick_global=tick_index_global,
                        path=str(path),
                        duration_sec=_t.monotonic() - _t0,
                        rss_before_mb=_rss_before,
                        rss_peak_during_mb=max(_rss_before, _rss_after),
                        rss_after_mb=_rss_after,
                        events_evicted_before_write=evicted_before_write,
                    )
            except Exception:  # noqa: BLE001
                pass
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
                tick_metrics_recorder_state=(
                    self._tick_metrics_recorder.to_snapshot_state()
                    if self._tick_metrics_recorder is not None else {}
                ),
                dialogue_service_state=(
                    self._dialogue_service.to_snapshot_state()
                    if self._dialogue_service is not None else {}
                ),
                # 2026-05-21 RESUME-DETERMINISM D
                conversation_service_state=(
                    getattr(self._memory_service, "_conversation").to_snapshot_state()
                    if (
                        self._memory_service is not None
                        and getattr(self._memory_service, "_conversation", None)
                        is not None
                    )
                    else {}
                ),
                rng_state={},
                pending_ops_meta={},
                provider=self._provider_name,
                # 2026-05-21 R4 (ledger-anchor-on-resume): graceful-stop
                # final snapshot also carries the anchor.
                start_date_anchor_iso=(
                    self._start_date_anchor.isoformat()
                    if getattr(self, "_start_date_anchor", None) is not None
                    else None
                ),
            )
            # 2026-05-21 R1 (fix-snapshot-filename-spawn-collision):
            # graceful-stop final snapshot ALSO gets PID prefix so multiple
            # graceful-stop events across spawns don't overwrite each other.
            import os as _os_final
            spawn_id = getattr(self, "_spawn_id", None) or _os_final.getpid()
            self._spawn_id = spawn_id
            path = self._output_dir / (
                f"seed_{self._seed}_pid{spawn_id}_tick_final.snapshot.json"
            )
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
        day 的部分 tick 数据）。No-op if no day has completed yet —
        the setup-phase abort sentinel is written by run_multi_day's
        post-finally block, not here (see harden-worker-resilience)."""
        if not per_day:
            logger.info(
                "MultiDayRunner: SIGUSR1 received before first day "
                "completed — no partial to write; setup-phase sentinel "
                "will be emitted by run_multi_day post-loop",
            )
            return
        last = per_day[-1]
        self._write_partial(
            day_index=last.day_index,
            simulated_date=last.simulated_date,
            per_day=per_day,
            agents_by_id=agents_by_id,
        )

    def _write_aborted_in_setup_sentinel(self) -> None:
        """harden-worker-resilience: write `seed_N.aborted_in_setup.json`
        so external audit / resume_publishable can distinguish
        "SIGUSR1 in setup-phase" from "normally INTERRUPTED with per-day
        partial". Sentinel is harmless to the next resume — the
        resume worker is expected to unlink it on startup.
        """
        if self._output_dir is None:
            return
        sentinel = (
            self._output_dir / f"seed_{self._seed}.aborted_in_setup.json"
        )
        payload = {
            "seed": self._seed,
            "aborted_at": datetime.utcnow().isoformat() + "Z",
            "reason": "SIGUSR1 received during setup phase",
            "completed_days": 0,
            "wal_writes": getattr(self._wal_writer, "write_count", 0)
                if self._wal_writer is not None else 0,
        }
        try:
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.warning(
                "Setup-phase abort sentinel written to %s "
                "(SIGUSR1 received before first day completed)",
                sentinel,
            )
        except OSError as exc:
            logger.error(
                "Failed to write setup-phase abort sentinel: %s", exc,
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
