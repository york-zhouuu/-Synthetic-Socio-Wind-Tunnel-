"""
SimulationCheckpoint — tick-level in-memory state 序列化与还原。

run-resilience（2026-05-15）的 per-day partial 只能定位"完整 day 结束"
的状态，且 `--resume` 实际并不还原 in-memory state。本模块补齐这两个
缺口：

- per-tick WAL append（独立诊断信号）
- per-N-tick SimulationCheckpoint snapshot（完整状态 dump）
- restore_into 把 state 灌回 ledger / agents / memory / attention 四个子系统
- RNG 状态在 snapshot/restore 中保留，保证恢复后下一步随机序列与原本一致

设计参见：openspec/specs/tick-level-resume/spec.md
"""

from __future__ import annotations

import json
import logging
import os
import random as _random
import tempfile
from datetime import date as date_cls, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from synthetic_socio_wind_tunnel.run_resilience.checkpoint import (
    IncompatibleCheckpointError,
)

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.runtime import AgentRuntime
    from synthetic_socio_wind_tunnel.attention.service import AttentionService
    from synthetic_socio_wind_tunnel.ledger.service import Ledger
    from synthetic_socio_wind_tunnel.memory.service import MemoryService
    from synthetic_socio_wind_tunnel.orchestrator.service import Orchestrator

logger = logging.getLogger(__name__)


_CURRENT_SCHEMA_VERSION = "3"
# v3 (2026-05-19, capability 1.12): adds dialogue_service_state so agent
#   dialogue content + DialogueMessage history survives kill+resume.
# v2 (2026-05-19, capability 1.11): adds tick_metrics_recorder_state so
#   resume preserves accumulated per_day_summaries / encounter / dwell
#   counters across kill+resume cycles.
# v1 (initial, 2026-05-16, capability tick-level-resume): base shape.
#
# Backwards compat: v1 and v2 snapshots SHALL be readable — missing fields
# default to {} (empty per-day buckets / empty dialogue store). This means
# resuming an old snapshot will start with no historical metrics + no
# dialogue history (matching prior behavior, since those weren't captured).
_READABLE_SCHEMA_VERSIONS = {"1", "2", "3"}


# ---------------------------------------------------------------------------
# RNG state capture / restore
# ---------------------------------------------------------------------------

def _rng_state_to_json(state: tuple[Any, ...]) -> list[Any]:
    """`random.Random.getstate()` 返回 nested tuple (version, internal, gauss_next)
    其中 internal 也是 tuple of ints。tuple 不是 JSON-primitive 所以递归转 list。"""
    return [_rng_state_to_json(v) if isinstance(v, tuple) else v for v in state]


def _rng_state_from_json(state: list[Any]) -> tuple[Any, ...]:
    """list → tuple 反向。"""
    return tuple(_rng_state_from_json(v) if isinstance(v, list) else v for v in state)


def capture_rng(named: Mapping[str, _random.Random]) -> dict[str, list[Any]]:
    """对每个 named Random 实例 getstate() 并转为 JSON-safe list。

    返回 dict 的 key 是调用方提供的 namespace（如 "orchestrator" /
    "collapse" / "policy_hack"）。
    """
    out: dict[str, list[Any]] = {}
    for name, rng in named.items():
        try:
            out[name] = _rng_state_to_json(rng.getstate())
        except Exception as exc:  # noqa: BLE001
            logger.warning("capture_rng: %s.getstate() failed: %s", name, exc)
    return out


def restore_rng(
    state: Mapping[str, list[Any]],
    named: Mapping[str, _random.Random],
) -> None:
    """把 state[name] 灌回 named[name] 的 Random 实例。

    missing key SHALL log warning 而不 raise——子系统可继续用默认 RNG，
    重现性会下降但 simulation 不会崩。
    """
    for name, rng in named.items():
        raw = state.get(name)
        if raw is None:
            logger.warning(
                "restore_rng: %r 在 snapshot 中缺失 RNG state；该子系统将"
                "使用当前 RNG 状态继续（重现性受影响）", name,
            )
            continue
        try:
            rng.setstate(_rng_state_from_json(list(raw)))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "restore_rng: %r setstate 失败 (%s)；该子系统继续用当前 state",
                name, exc,
            )


# ---------------------------------------------------------------------------
# SnapshotPolicy — 频率与保留策略
# ---------------------------------------------------------------------------

class SnapshotPolicy(BaseModel):
    """Snapshot 写盘策略；MultiDayRunner 构造时注入。"""

    model_config = ConfigDict(frozen=True)

    every_ticks: int = Field(default=24, ge=0, le=288)
    """每 N global-tick 写一次 snapshot。0 = 禁用 snapshot（向后兼容
    run-resilience partial-only 行为）。"""

    keep_last_k: int = Field(default=1, ge=1, le=100)
    """滚动保留最近 K 个 snapshot；新 snapshot 落盘后清更早的。

    Default 1 (backlog 1.7 G, 2026-05-19): publishable snapshot 是 1.7-3.5 GB
    每个；keep_last_k=2 = 每 cell 平均 5 GB 闲置磁盘。一份 snapshot 已经够
    resume，多一份给"上次失败 fallback"在实践中价值低于磁盘成本。env
    `RESILIENCE_SNAPSHOT_KEEP_LAST=2` 可恢复旧行为。"""

    wal_enabled: bool = True
    """per-tick WAL 写盘开关。"""

    wal_fsync_every_ticks: int = Field(default=1, ge=0)
    """0 = 永不 fsync；1 = 每 tick fsync；N = 每 N tick fsync。"""

    @classmethod
    def from_env(cls) -> SnapshotPolicy:
        """从 RESILIENCE_SNAPSHOT_* / RESILIENCE_WAL_* 环境变量构造。"""
        return cls(
            every_ticks=_env_int("RESILIENCE_SNAPSHOT_EVERY_TICKS", cls.model_fields["every_ticks"].default),
            keep_last_k=_env_int("RESILIENCE_SNAPSHOT_KEEP_LAST", cls.model_fields["keep_last_k"].default),
            wal_enabled=_env_bool("RESILIENCE_WAL_ENABLED", cls.model_fields["wal_enabled"].default),
            wal_fsync_every_ticks=_env_int(
                "RESILIENCE_WAL_FSYNC_EVERY_TICKS",
                cls.model_fields["wal_fsync_every_ticks"].default,
            ),
        )


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("%s=%r 无法解析为 int，使用默认 %s", key, raw, default)
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    v = raw.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    logger.warning("%s=%r 无法解析为 bool，使用默认 %s", key, raw, default)
    return default


# ---------------------------------------------------------------------------
# SimulationCheckpoint — 完整 state snapshot
# ---------------------------------------------------------------------------

class SimulationCheckpoint(BaseModel):
    """完整 in-memory state 的 frozen 快照。

    通过 `write_atomic(path)` 落盘到
    `<output_dir>/seed_{seed}_tick{tick_index_global}.snapshot.json`；
    通过 `read(path)` 读回；通过 `restore_into(...)` 灌回 in-memory 对象。
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = _CURRENT_SCHEMA_VERSION
    seed: int
    tick_index: int
    """tick_index_global = day_index * ticks_per_day + intra_day_tick"""
    day_index: int
    simulated_time: datetime

    ledger_state: dict[str, Any] = Field(default_factory=dict)
    agent_runtime_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """agent_id → 该 agent 的 to_snapshot_state() 输出。"""
    memory_store_state: dict[str, Any] = Field(default_factory=dict)
    attention_service_state: dict[str, Any] = Field(default_factory=dict)
    tick_metrics_recorder_state: dict[str, Any] = Field(default_factory=dict)
    """Accumulated per-day buckets — preserved across kill+resume so the
    final seed_X.json reflects ALL days run, not just the last cycle.
    Added 2026-05-19 (capability 1.11)."""
    dialogue_service_state: dict[str, Any] = Field(default_factory=dict)
    """Bilateral dialogues + DialogueMessage history. Without this the
    "agent 之间的故事" narrative output is lost on resume.
    Added 2026-05-19 (capability 1.12)."""
    rng_state: dict[str, list[Any]] = Field(default_factory=dict)

    pending_ops_meta: dict[str, Any] = Field(default_factory=dict)
    """In-flight OperationPool ops 元数据；restore 时全部 abandon，本字段仅诊断用。"""

    # 2026-05-21 R4 (ledger-anchor-on-resume): preserve the original
    # start_date so resume can detect ledger.current_time drift caused
    # by watchdog auto-resume from a divergent ledger state. Optional
    # for back-compat with legacy snapshots (None = drift check skipped).
    start_date_anchor_iso: str | None = None
    """ISO-format date (YYYY-MM-DD) of the run's original day-0 start.
    Set by MultiDayRunner when writing the snapshot. None for legacy
    snapshots — resume's drift check silently skipped in that case."""

    provider: str = "stub"
    """记录产生该 snapshot 的 LLM provider，与 run-resilience partial 同语义。"""

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # ---- I/O ----

    def write_atomic(self, path: Path) -> Path:
        """原子写盘：先写唯一 tmp 文件、fsync、然后 os.replace。

        SIGKILL 期间目标路径 SHALL 要么不存在、要么是合法 JSON——不会
        出现写到一半的破损文件。

        harden-worker-resilience (2026-05-19): 历史实现用固定
        `path.suffix + ".tmp"` tmp 文件名，多进程 / 多线程写同一 path
        时（如 LaunchAgent 误判 PID 死亡导致 double-spawn）会互相
        踩在同一 tmp 上：进程 A 写完 rename，进程 B 的 os.replace
        FileNotFoundError；更糟时撕裂 JSON。改为
        `tempfile.NamedTemporaryFile(dir=parent)` 让 OS 保证 tmp 名唯一。
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        body = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            default=str,
        )

        # 唯一 tmp 文件名（OS 保证），同 parent 保证 os.replace 是同卷
        # 的原子 rename。delete=False 因为我们要把它 rename 出来。
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(body)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
        except Exception:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise

        try:
            os.replace(tmp_path, path)
        except OSError:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise
        return path

    @classmethod
    def read(cls, path: Path) -> SimulationCheckpoint:
        """读 + schema 校验。

        v1, v2, v3 都可读（_READABLE_SCHEMA_VERSIONS）—— 旧 snapshot 缺
        失的字段（tick_metrics_recorder_state / dialogue_service_state）
        默认为 {}，Pydantic 接受 default_factory。

        其它版本（未来不兼容变更 / 损坏文件）raise IncompatibleCheckpointError。
        """
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        found = str(payload.get("schema_version", ""))
        if found not in _READABLE_SCHEMA_VERSIONS:
            raise IncompatibleCheckpointError(
                expected=_CURRENT_SCHEMA_VERSION,
                found=found,
                path=path,
            )
        # If reading an older schema, upgrade in-place so model_validate
        # gets a consistent v3-shaped payload. Pydantic would default
        # missing fields anyway, but bumping schema_version normalizes
        # what we hold in memory + what get re-written if this snapshot
        # is rewritten.
        if found != _CURRENT_SCHEMA_VERSION:
            payload["schema_version"] = _CURRENT_SCHEMA_VERSION
            payload.setdefault("tick_metrics_recorder_state", {})
            payload.setdefault("dialogue_service_state", {})
        return cls.model_validate(payload)

    # ---- restore orchestration ----

    def restore_into(
        self,
        *,
        orchestrator: "Orchestrator | None" = None,
        ledger: "Ledger | None" = None,
        agents: Mapping[str, "AgentRuntime"] | None = None,
        memory_service: "MemoryService | None" = None,
        attention_service: "AttentionService | None" = None,
        tick_metrics_recorder: Any = None,
        dialogue_service: Any = None,
        named_rngs: Mapping[str, _random.Random] | None = None,
    ) -> None:
        """把 snapshot 完整还原到 in-memory 对象。

        顺序：ledger → agents → memory → attention → rng。
        memory_service / attention_service / named_rngs 为 None 时跳过对应步骤。
        缺失 agent → raise ValueError 指出缺失 id。
        """
        # 1. Ledger
        if ledger is not None and self.ledger_state:
            ledger.from_snapshot_state(self.ledger_state)

        # 2. Agents
        if agents is not None and self.agent_runtime_states:
            missing = [
                aid for aid in self.agent_runtime_states
                if aid not in agents
            ]
            if missing:
                raise ValueError(
                    f"restore_into: snapshot has {len(missing)} agents missing "
                    f"from runtime: {missing[:5]}{'...' if len(missing) > 5 else ''}",
                )
            for aid, state in self.agent_runtime_states.items():
                agent = agents[aid]
                agent.from_snapshot_state(state)

        # 3. Memory
        if memory_service is not None and self.memory_store_state:
            memory_service.from_snapshot_state(self.memory_store_state)

        # 4. Attention
        if attention_service is not None and self.attention_service_state:
            attention_service.from_snapshot_state(self.attention_service_state)

        # 4b. TickMetricsRecorder — preserves accumulated per-day buckets
        # across resume cycles (capability 1.11)
        if tick_metrics_recorder is not None and self.tick_metrics_recorder_state:
            tick_metrics_recorder.from_snapshot_state(
                self.tick_metrics_recorder_state,
            )

        # 4c. DialogueService — preserves dialogue + message history
        # for narrative output (capability 1.12)
        if dialogue_service is not None and self.dialogue_service_state:
            dialogue_service.from_snapshot_state(self.dialogue_service_state)

        # 5. RNGs (caller-provided mapping; cf. capture_rng)
        if named_rngs is not None and self.rng_state:
            restore_rng(self.rng_state, named_rngs)

        # 6. pending_ops_meta — abandon-and-retry; nothing to restore
        if self.pending_ops_meta:
            n = sum(
                len(v) if isinstance(v, list) else 1
                for v in self.pending_ops_meta.values()
            )
            logger.info(
                "restore_into: %d in-flight ops abandoned (will be re-triggered "
                "by normal agent path)", n,
            )

        # orchestrator hook — currently unused but reserved for future
        # tick counter rehydration
        _ = orchestrator


# ---------------------------------------------------------------------------
# Snapshot 文件命名 + 滚动清理
# ---------------------------------------------------------------------------

def snapshot_path(
    output_dir: Path, *, seed: int, tick_index_global: int,
    spawn_id: int | None = None,
) -> Path:
    """Compose the snapshot file path.

    2026-05-21 R1 (fix-snapshot-filename-spawn-collision): optionally
    prepend `pid<spawn_id>` so respawn doesn't overwrite earlier
    spawn's snapshots at colliding internal tick numbers.

    - `spawn_id=None` (default) → legacy `seed_<N>_tick<T>.snapshot.json`
      (back-compat for existing callers + tests)
    - `spawn_id=<int>` → `seed_<N>_pid<spawn_id>_tick<T>.snapshot.json`

    The PID is the writing process's `os.getpid()`. Two distinct workers
    naturally have different PIDs → different filenames → no collision.
    """
    if spawn_id is None:
        return output_dir / f"seed_{seed}_tick{tick_index_global}.snapshot.json"
    return output_dir / (
        f"seed_{seed}_pid{spawn_id}_tick{tick_index_global}.snapshot.json"
    )


def find_latest_snapshot(output_dir: Path, *, seed: int) -> Path | None:
    """Find the most-recently-written snapshot for `seed`.

    2026-05-21 R1 (fix-snapshot-filename-spawn-collision): selection
    moved from "highest numeric tick" to "latest mtime". Reason:
    PID-prefixed snapshots (`seed_<N>_pid<PID>_tick<T>.snapshot.json`)
    from a newer respawn can have a LOWER internal tick number than
    an older spawn's snapshot — but the newer file IS the right resume
    point.

    Recognized formats (both):
    - `seed_<N>_tick<T>.snapshot.json` (legacy, no PID)
    - `seed_<N>_pid<PID>_tick<T>.snapshot.json` (PID-prefixed)
    - `seed_<N>_tick_final.snapshot.json` (graceful_stop final)
    - `seed_<N>_pid<PID>_tick_final.snapshot.json` (graceful_stop final
      from PID-aware spawn)

    Selection rule:
    1. Among all matching files, pick the one with the latest mtime.
    2. tick_final files participate on equal footing — their authority
       comes from being the latest write at graceful_stop time, which
       is captured by mtime anyway.
    """
    if not output_dir.exists():
        return None
    import re as _re
    pattern = _re.compile(
        rf"^seed_{seed}(?:_pid\d+)?_tick(?P<tick>_final|\d+)\.snapshot\.json$"
    )
    matched: list[tuple[float, int, Path]] = []
    for p in output_dir.glob(f"seed_{seed}_*.snapshot.json"):
        m = pattern.match(p.name)
        if not m:
            continue
        tick_str = m.group("tick")
        # tick_final → effectively highest tick (graceful_stop authority)
        tick_num = -1 if tick_str == "_final" else int(tick_str)
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        # tick_final wins tiebreaker → use a huge number
        tiebreak = (10**12) if tick_str == "_final" else tick_num
        matched.append((mtime, tiebreak, p))
    if not matched:
        return None
    # Sort by (mtime, tick_tiebreak) ascending; last is latest write
    # → if multiple files share the same mtime, the one with higher
    # tick number wins (preserves "pick highest tick" intent when
    # files were created in rapid succession).
    matched.sort(key=lambda t: (t[0], t[1]))
    return matched[-1][2]


def prune_snapshots(output_dir: Path, *, seed: int, keep: int) -> list[Path]:
    """Keep the K most-recently-written snapshots for `seed`; delete rest.

    2026-05-21 R1 (fix-snapshot-filename-spawn-collision): selection
    moved from "highest tick number" to "newest mtime" to handle
    PID-prefixed filenames where two spawns can have overlapping tick
    ranges. Recognizes both legacy and PID-prefixed formats; also
    recognizes `_tick_final` variants.

    Returns the list of deleted paths.
    """
    if not output_dir.exists() or keep <= 0:
        return []
    import re as _re
    pattern = _re.compile(
        rf"^seed_{seed}(?:_pid\d+)?_tick(?:_final|\d+)\.snapshot\.json$"
    )
    candidates: list[Path] = []
    for p in output_dir.glob(f"seed_{seed}_*.snapshot.json"):
        if pattern.match(p.name):
            candidates.append(p)
    if len(candidates) <= keep:
        return []
    # Sort by mtime ascending; oldest at front
    try:
        candidates.sort(key=lambda p: p.stat().st_mtime)
    except OSError:
        candidates.sort(key=lambda p: p.name)
    to_delete = candidates[:-keep]  # keep newest K (last in list)
    deleted: list[Path] = []
    for p in to_delete:
        try:
            p.unlink()
            deleted.append(p)
        except OSError as exc:
            logger.warning("无法删除老 snapshot %s: %s", p, exc)
    return deleted


# ---------------------------------------------------------------------------
# Per-tick WAL
# ---------------------------------------------------------------------------

def wal_path(output_dir: Path, *, seed: int) -> Path:
    return output_dir / f"seed_{seed}.wal.jsonl"


class WALWriter:
    """Append-only per-tick WAL。

    每行 JSON ~100 B。fsync 频率由 SnapshotPolicy.wal_fsync_every_ticks 控制。
    open 一次、整 run 复用——避免每 tick 都 open/close 浪费 syscall。
    """

    def __init__(
        self,
        *,
        output_dir: Path,
        seed: int,
        fsync_every_ticks: int = 1,
    ) -> None:
        self._path = wal_path(output_dir, seed=seed)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fsync_every = max(0, fsync_every_ticks)
        self._lines_since_fsync = 0
        self._fp = self._path.open("a", encoding="utf-8")

    def append(
        self,
        *,
        tick_index: int,
        day_index: int,
        simulated_time: datetime,
        commits_succeeded: int,
        commits_failed: int,
        encounter_count: int,
        snapshot_path: Path | None = None,
        wall_clock: datetime | None = None,
    ) -> None:
        line = json.dumps(
            {
                "tick_index": tick_index,
                "day_index": day_index,
                "simulated_time": simulated_time.isoformat(),
                "wall_clock": (wall_clock or datetime.utcnow()).isoformat(),
                "commits_succeeded": commits_succeeded,
                "commits_failed": commits_failed,
                "encounter_count": encounter_count,
                "snapshot_path": str(snapshot_path) if snapshot_path else None,
            },
            ensure_ascii=False,
        )
        try:
            self._fp.write(line + "\n")
            self._lines_since_fsync += 1
            if self._fsync_every > 0 and self._lines_since_fsync >= self._fsync_every:
                self._fp.flush()
                try:
                    os.fsync(self._fp.fileno())
                except OSError:
                    pass
                self._lines_since_fsync = 0
        except OSError as exc:
            logger.warning(
                "WAL append failed at tick=%d day=%d: %s",
                tick_index, day_index, exc,
            )

    def close(self) -> None:
        try:
            self._fp.flush()
            self._fp.close()
        except OSError:
            pass

    def __enter__(self) -> "WALWriter":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def read_last_wal_line(path: Path) -> dict[str, Any] | None:
    """读 WAL 最后一行（用于 audit / resume 进度）；空文件返 None。

    实现：seek 到末尾、向前找最后一个 newline；性能 O(line length)。
    """
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return None
            # 简单实现：读最后 8 KB（典型 WAL 一行 < 500 B），split 取最后非空
            read_back = min(size, 8192)
            f.seek(size - read_back)
            tail = f.read(read_back).decode("utf-8", errors="replace")
        lines = [ln for ln in tail.splitlines() if ln.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except (OSError, ValueError) as exc:
        logger.warning("读 WAL 最后一行失败 %s: %s", path, exc)
        return None
