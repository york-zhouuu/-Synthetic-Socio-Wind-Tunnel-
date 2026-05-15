"""
run_resilience — publishable run 的抗故障基础设施。

D1' 事故（2026-05-15 Gemini 连接池死锁）后引入，目标：
    1. 连接池硬化（keepalive=0 + 周期回收）阻断 CLOSE_WAIT 累积
    2. 统一 RetryPolicy + per-key 熔断
    3. Per-day checkpoint 使最坏损失 ≤ 1 模拟天
    4. SIGUSR1 graceful-stop 协议（"热修复"）
    5. HealthAudit 探活 + preflight 1000-agent smoke gate

参见：openspec/specs/run-resilience/spec.md
"""

from synthetic_socio_wind_tunnel.run_resilience.checkpoint import (
    DayCheckpointWriter,
    IncompatibleCheckpointError,
)
from synthetic_socio_wind_tunnel.run_resilience.circuit_breaker import (
    AllKeysOpenError,
    PerKeyCircuitBreaker,
)
from synthetic_socio_wind_tunnel.run_resilience.health import (
    DefaultSystemProbe,
    HealthAudit,
    HealthAuditReport,
    WorkerSnapshot,
)
from synthetic_socio_wind_tunnel.run_resilience.hotfix import HotfixSignalHandler
from synthetic_socio_wind_tunnel.run_resilience.retry import RetryPolicy
from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
    SimulationCheckpoint,
    SnapshotPolicy,
    WALWriter,
    capture_rng,
    find_latest_snapshot,
    prune_snapshots,
    read_last_wal_line,
    restore_rng,
    snapshot_path,
    wal_path,
)

__all__ = [
    "AllKeysOpenError",
    "DayCheckpointWriter",
    "DefaultSystemProbe",
    "HealthAudit",
    "HealthAuditReport",
    "HotfixSignalHandler",
    "IncompatibleCheckpointError",
    "PerKeyCircuitBreaker",
    "RetryPolicy",
    "SimulationCheckpoint",
    "SnapshotPolicy",
    "WALWriter",
    "WorkerSnapshot",
    "capture_rng",
    "find_latest_snapshot",
    "prune_snapshots",
    "read_last_wal_line",
    "restore_rng",
    "snapshot_path",
    "wal_path",
]
