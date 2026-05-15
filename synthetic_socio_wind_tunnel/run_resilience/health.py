"""
HealthAudit — 对 in-progress run 做单次"探活"健康检查。

D1' 事故里 3/4 worker 死锁 7+ 小时无新 log 才被人发现。本模块提供
单一入口扫描一个 run 目录的所有 worker pid，按多维信号（process state /
log 静默时长 / CLOSE_WAIT 累积）判定健康状态：

    healthy → 一切正常
    warning → 单一维度告警（如静默 30 min）
    suspected_deadlock → 多维度同时告警，建议人工 SIGUSR1 + resume

输出主要由 `tools/audit_run_health.py` CLI 消费；也可被 launchd / cron
直接调起或写入 CI。

实现选择：用 subprocess 调 ps / lsof 而不依赖 psutil——保持本模块零新增
依赖，且 D1' 事故现场用的就是 `ps -o stat,rss` + `lsof -i -p`。
"""

from __future__ import annotations

import logging
import os
import re
import resource
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


WorkerStatus = Literal["healthy", "warning", "suspected_deadlock"]


_DEFAULT_SILENT_WARN_S = 1800.0      # 30 min
_DEFAULT_SILENT_DEADLOCK_S = 3600.0  # 60 min
_DEFAULT_CLOSE_WAIT_WARN_RATIO = 0.6
_DEFAULT_CLOSE_WAIT_DEADLOCK_RATIO = 0.9
# tick-level-resume (2026-05-16)
_DEFAULT_TICK_SECONDS_EXPECTED = 5.0  # 1 tick ≈ 5s wall in 1000-agent DeepSeek
_DEFAULT_STUCK_WARN_FACTOR = 10.0     # 10× expected = rising_wal_silence
_DEFAULT_STUCK_DEADLOCK_FACTOR = 30.0  # 30× expected = suspected_stuck


class WorkerSnapshot(BaseModel):
    """单个 worker 的探活快照。"""

    model_config = ConfigDict(frozen=True)

    pid: int
    process_state: str | None = None          # `ps -o stat` 输出，e.g. "R", "U", "S"
    log_path: Path | None = None
    last_log_mtime_seconds_ago: float | None = None
    close_wait_count: int | None = None
    rss_bytes: int | None = None
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    status: WorkerStatus = "healthy"


class HealthAuditReport(BaseModel):
    """整个 run 的健康报告。"""

    model_config = ConfigDict(frozen=True)

    run_dir: Path
    workers: tuple[WorkerSnapshot, ...]
    overall_status: WorkerStatus
    audited_at: datetime
    notes: tuple[str, ...] = Field(default_factory=tuple)


class _SystemProbe(Protocol):
    """ps/lsof/log 等系统访问的抽象层——便于测试注入 mock。"""

    def process_state(self, pid: int) -> str | None: ...
    def rss_bytes(self, pid: int) -> int | None: ...
    def close_wait_count(self, pid: int) -> int | None: ...
    def log_mtime(self, log_path: Path) -> float | None: ...
    def now(self) -> datetime: ...
    def nofile_limit(self) -> int: ...


class DefaultSystemProbe:
    """生产环境实现——subprocess + os.stat。"""

    def process_state(self, pid: int) -> str | None:
        try:
            out = subprocess.check_output(
                ["ps", "-o", "stat=", "-p", str(pid)],
                text=True, timeout=5, stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return None
        return out or None

    def rss_bytes(self, pid: int) -> int | None:
        try:
            out = subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(pid)],
                text=True, timeout=5, stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return None
        try:
            return int(out) * 1024  # ps 给 KB
        except ValueError:
            return None

    def close_wait_count(self, pid: int) -> int | None:
        try:
            out = subprocess.check_output(
                ["lsof", "-i", "-p", str(pid), "-nP"],
                text=True, timeout=10, stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return None
        return sum(1 for line in out.splitlines() if "CLOSE_WAIT" in line)

    def log_mtime(self, log_path: Path) -> float | None:
        try:
            return log_path.stat().st_mtime
        except OSError:
            return None

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def nofile_limit(self) -> int:
        try:
            soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
            return int(soft)
        except (ValueError, OSError):
            return 1024


_PID_RE = re.compile(r"pid[ =:]+(\d+)", re.IGNORECASE)


class HealthAudit:
    """运行单次探活；阈值通过环境变量配置（RESILIENCE_HEALTH_*）。"""

    def __init__(
        self,
        *,
        silent_warn_seconds: float | None = None,
        silent_deadlock_seconds: float | None = None,
        close_wait_warn_ratio: float | None = None,
        close_wait_deadlock_ratio: float | None = None,
        tick_seconds_expected: float | None = None,
        stuck_warn_factor: float | None = None,
        stuck_deadlock_factor: float | None = None,
        probe: _SystemProbe | None = None,
    ) -> None:
        self.silent_warn_seconds = _env_float(
            "RESILIENCE_HEALTH_SILENT_WARN_SECONDS",
            silent_warn_seconds, _DEFAULT_SILENT_WARN_S,
        )
        self.silent_deadlock_seconds = _env_float(
            "RESILIENCE_HEALTH_SILENT_DEADLOCK_SECONDS",
            silent_deadlock_seconds, _DEFAULT_SILENT_DEADLOCK_S,
        )
        self.close_wait_warn_ratio = _env_float(
            "RESILIENCE_HEALTH_CLOSE_WAIT_WARN_RATIO",
            close_wait_warn_ratio, _DEFAULT_CLOSE_WAIT_WARN_RATIO,
        )
        self.close_wait_deadlock_ratio = _env_float(
            "RESILIENCE_HEALTH_CLOSE_WAIT_DEADLOCK_RATIO",
            close_wait_deadlock_ratio, _DEFAULT_CLOSE_WAIT_DEADLOCK_RATIO,
        )
        # tick-level-resume (2026-05-16): WAL progress thresholds
        self.tick_seconds_expected = _env_float(
            "RESILIENCE_HEALTH_TICK_SECONDS_EXPECTED",
            tick_seconds_expected, _DEFAULT_TICK_SECONDS_EXPECTED,
        )
        self.stuck_warn_factor = _env_float(
            "RESILIENCE_HEALTH_STUCK_WARN_FACTOR",
            stuck_warn_factor, _DEFAULT_STUCK_WARN_FACTOR,
        )
        self.stuck_deadlock_factor = _env_float(
            "RESILIENCE_HEALTH_STUCK_DEADLOCK_FACTOR",
            stuck_deadlock_factor, _DEFAULT_STUCK_DEADLOCK_FACTOR,
        )
        self.probe: _SystemProbe = probe or DefaultSystemProbe()

    def audit(self, run_dir: Path) -> HealthAuditReport:
        """扫描 run_dir 下的 worker_*.log 文件，提取 pid 后做单次健康检查。"""
        now = self.probe.now()
        notes: list[str] = []
        workers: list[WorkerSnapshot] = []

        for log_path in sorted(run_dir.glob("worker_*.log")):
            pid = _discover_pid(log_path)
            if pid is None:
                notes.append(f"无法从 {log_path.name} 解析出 pid")
                continue
            snapshot = self._audit_pid(pid=pid, log_path=log_path, now=now)
            workers.append(snapshot)

        # pids.json 备用通道（worker log 没写 pid 时）
        pids_json = run_dir / "pids.json"
        if pids_json.exists() and not workers:
            try:
                import json
                extra = json.loads(pids_json.read_text())
                for pid in extra.get("workers", []):
                    snapshot = self._audit_pid(pid=int(pid), log_path=None, now=now)
                    workers.append(snapshot)
            except (OSError, ValueError) as exc:
                notes.append(f"pids.json 解析失败: {exc}")

        # tick-level-resume: WAL silence check augments each worker's reasons.
        # The newest WAL file mtime relative to `now` indicates if the suite
        # is making progress. If WAL is too old → flag all workers as stuck.
        wal_reason = self._check_wal_progress(run_dir, now=now)
        if wal_reason is not None and workers:
            workers = [
                WorkerSnapshot(
                    pid=w.pid,
                    process_state=w.process_state,
                    log_path=w.log_path,
                    last_log_mtime_seconds_ago=w.last_log_mtime_seconds_ago,
                    close_wait_count=w.close_wait_count,
                    rss_bytes=w.rss_bytes,
                    reasons=tuple(list(w.reasons) + [wal_reason]),
                    status=_verdict(list(w.reasons) + [wal_reason]),
                )
                for w in workers
            ]

        overall = self._aggregate(workers)
        if not workers:
            overall = "warning"
            notes.append("无 worker 发现：run_dir 中既无 worker_*.log 也无 pids.json")
        return HealthAuditReport(
            run_dir=run_dir,
            workers=tuple(workers),
            overall_status=overall,
            audited_at=now,
            notes=tuple(notes),
        )

    def _check_wal_progress(
        self, run_dir: Path, *, now: datetime,
    ) -> str | None:
        """Scan run_dir recursively for *.wal.jsonl; return a reason string
        if the newest WAL mtime is old enough to flag, else None."""
        try:
            wal_files = list(run_dir.rglob("seed_*.wal.jsonl"))
        except OSError:
            return None
        if not wal_files:
            return None
        newest_mtime = max(
            (self.probe.log_mtime(p) or 0.0) for p in wal_files
        )
        if newest_mtime == 0.0:
            return None
        silence_s = max(0.0, now.timestamp() - newest_mtime)
        deadlock_threshold = self.tick_seconds_expected * self.stuck_deadlock_factor
        warn_threshold = self.tick_seconds_expected * self.stuck_warn_factor
        if silence_s >= deadlock_threshold:
            return "suspected_stuck"
        if silence_s >= warn_threshold:
            return "rising_wal_silence"
        return None

    def _audit_pid(
        self, *, pid: int, log_path: Path | None, now: datetime,
    ) -> WorkerSnapshot:
        reasons: list[str] = []
        state = self.probe.process_state(pid)
        rss = self.probe.rss_bytes(pid)
        close_wait = self.probe.close_wait_count(pid)

        silent_seconds: float | None = None
        if log_path is not None:
            mtime = self.probe.log_mtime(log_path)
            if mtime is not None:
                silent_seconds = max(0.0, now.timestamp() - mtime)

        if state is None:
            reasons.append("process_not_found")
        else:
            # macOS 'U' / Linux 'D' = uninterruptible sleep（危险，常见于死锁）
            if any(ch in state.upper() for ch in ("U", "D")):
                reasons.append("uninterruptible_state")

        if silent_seconds is not None:
            if silent_seconds >= self.silent_deadlock_seconds:
                reasons.append("silent_60min")
            elif silent_seconds >= self.silent_warn_seconds:
                reasons.append("silent_30min")

        if close_wait is not None:
            limit = self.probe.nofile_limit()
            ratio = close_wait / max(1, limit)
            if ratio >= self.close_wait_deadlock_ratio:
                reasons.append("high_close_wait")
            elif ratio >= self.close_wait_warn_ratio:
                reasons.append("rising_close_wait")

        status = _verdict(reasons)
        return WorkerSnapshot(
            pid=pid,
            process_state=state,
            log_path=log_path,
            last_log_mtime_seconds_ago=silent_seconds,
            close_wait_count=close_wait,
            rss_bytes=rss,
            reasons=tuple(reasons),
            status=status,
        )

    @staticmethod
    def _aggregate(workers: list[WorkerSnapshot]) -> WorkerStatus:
        if not workers:
            return "warning"
        if any(w.status == "suspected_deadlock" for w in workers):
            return "suspected_deadlock"
        if any(w.status == "warning" for w in workers):
            return "warning"
        return "healthy"


_DEADLOCK_REASONS: frozenset[str] = frozenset({
    "silent_60min",
    "high_close_wait",
    "uninterruptible_state",
    "process_not_found",
    # tick-level-resume (2026-05-16)
    "suspected_stuck",
})


def _verdict(reasons: list[str]) -> WorkerStatus:
    """单 worker 的判定：≥2 个 deadlock 维度同时告警 → suspected_deadlock；
    1 个 deadlock 维度或任何 warning 维度 → warning；空 → healthy。"""
    if not reasons:
        return "healthy"
    deadlock_hits = sum(1 for r in reasons if r in _DEADLOCK_REASONS)
    if deadlock_hits >= 2:
        return "suspected_deadlock"
    return "warning"


def _discover_pid(log_path: Path) -> int | None:
    """从 log 内容前 4 KB 搜 'pid 123' 风格的字符串。"""
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(4096)
    except OSError:
        return None
    match = _PID_RE.search(head)
    if match is None:
        return None
    return int(match.group(1))


def _env_float(env_key: str, override: float | None, default: float) -> float:
    if override is not None:
        return override
    raw = os.environ.get(env_key)
    if raw:
        try:
            return float(raw)
        except ValueError:
            logger.warning("%s=%r 无法解析，使用默认 %s", env_key, raw, default)
    return default
