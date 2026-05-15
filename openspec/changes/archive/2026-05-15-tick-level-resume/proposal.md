## Why

刚 archive 的 `run-resilience`（2026-05-15）做了 per-day checkpoint +
SIGUSR1 graceful stop + `--resume`，但有两个未关上的缺口：

1. **`--resume` 不真正还原 in-memory state**。当前
   `MultiDayRunner(resume_from=5)` 只是把循环起点设为 day 5，**不**从
   partial JSON 把 Ledger / AgentRuntime / MemoryStore / AttentionService
   灌回 day-4-end 的状态——它从 fresh atlas 重新构造 day-0 起始 state。
   day 5 的起始 state 与原 day 4 结束 state **不一致**；前后两段数据拼接
   有 seam，对 14-day 协议的实验信号（memory carryover、agent 长期位置
   演化）造成系统性偏差。
2. **粒度只到天**。SIGKILL / crash / 断电发生在 day 5 tick 100 → 当天 100
   个 tick（≈8 simulated hour）的进度全丢；`--resume` 只能从 day 6 起。
   对 D2-D3 级 publishable run（60-80h wall time），1 天 = ~5h wall——
   不能接受"任何中断 = 5h 起步损失"。

用户原话："如果真的中断了，可以沿着最后一次提交的内容可以继续跑下去"——
即 **SIGKILL / crash / 断电在 tick 任意时刻，resume 都能从该 tick 后继续，
state 与中断前一致**。

**Chain-Position**：`infrastructure`（与 `multi-day-simulation` /
`run-resilience` 同位；不引入新主边界）。

## What Changes

### 1. SimulationCheckpoint：完整 in-memory state 的序列化与还原（NEW）

新建 `synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py`：

- `SimulationCheckpoint`（Pydantic frozen）字段：
  - `schema_version: str = "1"`
  - `seed: int` / `tick_index: int` / `day_index: int` /
    `simulated_time: datetime`
  - `ledger_state: dict`（entity_states + item_states + door_states +
    door usage history 等所有 Atlas-外可变 state）
  - `agent_runtime_states: dict[agent_id, dict]`（current_location /
    current_plan / current_intent / emotional_state / current_tick_in_plan /
    movement_state / personality state（如果可变） 等）
  - `memory_store_state: dict`（MemoryStore 的全部：events / daily_summaries
    / reflections / per-agent identity / embeddings cache key list）
  - `attention_service_state: dict`（per-agent pending / consumed
    notifications + decay state）
  - `rng_state: dict`（orchestrator + policy_hack + collapse 各自的
    `random.Random.getstate()`，dict 按使用方分组）
  - `pending_ops_meta: dict`（在飞 OperationPool ops 的 kind / agent /
    created_at；resume 时全部 **abandon**，由 agent 自行重触发，避免半
    state machine 状态污染）

- `SimulationCheckpoint.write_atomic(path)` — 原子写（`.tmp` + `rename`）
- `SimulationCheckpoint.read(path)` — 反序列化 + schema_version 校验，
  不兼容版本 raise `IncompatibleCheckpointError`（来自 run-resilience）
- `SimulationCheckpoint.restore_into(*, orchestrator, ledger, agents,
  memory_service, attention_service)` — 把所有 state 灌回 in-memory
  对象，按 (ledger → agents → memory → attention → rng) 顺序

每个子系统 SHALL 提供 `to_snapshot_state() -> dict` 与
`from_snapshot_state(state: dict) -> None` 方法；state_snapshot 模块用
duck-typing 调用，避免循环依赖。

### 2. 频率策略：per-tick WAL + per-N-tick snapshot（NEW）

完整 snapshot 体积大（1000 agent × 14 day 单次 ~50-100 MB；× 4032 tick
= 200-400 GB 总写盘量不可接受）。分两层：

- **Per-tick WAL**：每 tick 末追加一行到 `seed_{S}.wal.jsonl`，每行 ~100 B：
  `{"tick_index": T, "day_index": D, "simulated_time": "...",
  "commits_succeeded": N1, "commits_failed": N2, "encounter_count": N3,
  "snapshot_path": "<path or null>"}`。
  WAL **MUST** 在 tick 状态写回 Ledger 之后、`on_tick_end` hook 之前 fsync。
  ~400 KB / seed for 14 day（成本可忽略）。
- **Per-N-tick snapshot**：每 N tick 写一次完整 SimulationCheckpoint 到
  `seed_{S}_tick{T}.snapshot.json`。默认 **N=24**（5-min tick 制下=hourly）。
  可由 `RESILIENCE_SNAPSHOT_EVERY_TICKS` 覆盖（最小 1=per tick；最大
  288=per day 等价 run-resilience partial）。
- **Snapshot 滚动保留**：只保留最近 **K=2** 个 snapshot 文件（覆盖至少 1
  整 day）。新 snapshot 落盘后 `cleanup_old_snapshots(seed, keep=K)`
  删旧的——防止 disk 无限增长。
- **Graceful-stop 写 final snapshot**：SIGUSR1 触发时无论是否在 N 整数倍，
  都 SHALL 强制写一个 snapshot 把当前 in-progress tick 的 state 落盘。

### 3. Resume protocol（NEW）

1. 读 `seed_{S}.wal.jsonl` 最后一行 → `T_w`（中断前最后完成的 tick）
2. 读最近 snapshot → `T_s ≤ T_w`
3. `SimulationCheckpoint.restore_into(...)` → in-memory state 回到 `T_s`
4. 若 `T_w > T_s`：**重放** ticks `T_s+1 .. T_w`（orchestrator.run() 在
   tick 上跑一遍）——LLM 路径上响应**不可严格重现**，接受 replay-drift
   为已知折扣（仍优于丢 24h simulated time）
5. 从 `T_w + 1` 继续正常 run

### 4. MultiDayRunner 集成（MODIFIED）

`MultiDayRunner.__init__` 新增参数：

- `snapshot_every_ticks: int = 24` — 0 时禁用 snapshot（向后兼容
  run-resilience 的 partial-only 行为）
- `wal_enabled: bool = True` — per-tick WAL 开关
- `restore_from: SimulationCheckpoint | None = None` — 调用方传入恢复点；
  与 `resume_from: int` 并存（resume_from 仅在 restore_from=None 时生效）

主循环每 tick 末追加：写 WAL → 视频率写 snapshot → 检查
`_graceful_stop_requested`（已存在）→ 进入下一 tick。
graceful stop 路径 SHALL 强写 final snapshot 后再 break。
启动时若 `restore_from is not None`：先 `restore_into(...)`、然后从
`restore_from.day_index, tick_index + 1` 起步主循环。

### 5. CLI 集成（NEW flag）

`tools/run_variant_suite.py` 新增 `--resume-strategy`：

- `auto`（默认）：snapshot 优先；找不到 snapshot 时降级到 per-day partial
  （run-resilience 旧行为）
- `snapshot-only`：只用 snapshot；无 snapshot 时 fail-fast 退出
- `partial-only`：忽略 snapshot，按 run-resilience per-day partial 跑
- `none`：从 day 0 全新跑（覆盖 `--resume` 检测）

`--resume` 现有行为保留，与 `--resume-strategy=auto` 等效。

### 6. 健康审计扩展（MODIFIED）

`tools/audit_run_health.py` 新增检测维度：

- 读 `seed_*.wal.jsonl` 最后一行的 wall-clock timestamp（来自 WAL 行写入
  时间，与 simulated_time 不同）。若距 `now` > 1 个 tick 预期时长 ×
  `stuck_factor`（默认 10）→ 标记 worker 为 `suspected_stuck`
- `suspected_stuck` 与 `suspected_deadlock` 并列为 deadlock-class 维度，
  贡献到 overall_status 判定

### 7. 各子系统的 to/from snapshot 接入（MODIFIED）

四个子系统加 `to_snapshot_state()` / `from_snapshot_state(state)`：

- `synthetic_socio_wind_tunnel.ledger.Ledger`
- `synthetic_socio_wind_tunnel.agent.runtime.AgentRuntime`
- `synthetic_socio_wind_tunnel.memory.service.MemoryService`（或 MemoryStore）
- `synthetic_socio_wind_tunnel.attention.service.AttentionService`

Atlas 不接入（只读、不变）。OperationPool 不接入（abandon-and-retry 策略）。

## Capabilities

### New Capabilities

- `tick-level-resume`: per-tick WAL + per-N-tick SimulationCheckpoint 落盘
  + restore_into 各子系统 + CLI `--resume-strategy` + audit `suspected_stuck`
  维度。对外公共类型：`SimulationCheckpoint` /
  `SnapshotPolicy`（Pydantic frozen, 含 every_ticks / keep_last_k 字段）。

### Modified Capabilities

- `multi-day-run`: MultiDayRunner 新增 `snapshot_every_ticks` /
  `wal_enabled` / `restore_from` 三个构造参数；主循环每 tick 末写 WAL +
  可选 snapshot；启动时若 restore_from 非空则先 restore_into

`run-resilience` 不动既有 SHALL 条款（per-day partial 仍 SHALL 写；本
change 在它之上叠加新粒度，二者层级化）。

## Impact

- **新代码**
  - `synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py`
    （SimulationCheckpoint + SnapshotPolicy + 各 serialize_* / restore_*
    helper + WAL writer/reader）
  - 四个子系统 `to_snapshot_state` / `from_snapshot_state` 方法（小补丁）
- **修改**
  - `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`：MultiDayRunner
    加 3 个构造参数 + 主循环 WAL/snapshot 写盘 + restore_from 路径
  - `synthetic_socio_wind_tunnel/orchestrator/service.py`：Orchestrator
    在每 tick 后暴露一个 hook 供 MultiDayRunner 写 WAL（已有 on_tick_end，
    复用即可）
  - `synthetic_socio_wind_tunnel/run_resilience/health.py`：新增
    `suspected_stuck` 维度 + WAL mtime 读
  - `tools/run_variant_suite.py`：`--resume-strategy` flag + auto-detect
    snapshot/WAL → 构造 `restore_from`
  - `tools/audit_run_health.py`：报告 WAL 进度 + `suspected_stuck`
  - `synthetic_socio_wind_tunnel/__init__.py` re-export `SimulationCheckpoint`
    / `SnapshotPolicy`
- **测试**
  - `tests/test_state_snapshot_round_trip.py`（各子系统 to/from state 双向
    一致）
  - `tests/test_tick_wal.py`（WAL append / read / 损坏恢复）
  - `tests/test_snapshot_lifecycle.py`（每 N tick 写 + cleanup keep K +
    final snapshot on graceful stop）
  - `tests/test_resume_from_snapshot.py`（端到端：跑 3 day → 中途 crash
    模拟 → snapshot+WAL → 新 runner restore → 继续跑完 → 最终 state
    与不中断时等价 / 接近）
  - `tests/test_run_variant_suite_resume_strategy.py`（CLI auto / snapshot-only
    / partial-only / none 4 个 strategy 行为）
  - `tests/test_audit_suspected_stuck.py`（WAL mtime 老 → suspected_stuck）
- **依赖**：无新增依赖
- **配置 / 文档**
  - `.env.example` 增加 `RESILIENCE_SNAPSHOT_EVERY_TICKS` /
    `RESILIENCE_SNAPSHOT_KEEP_LAST` 注释
  - `docs/agent_system/16-tick-level-resume.md`（用户向白话指南）
  - `CLAUDE.md` 关键不变量加一条
- **向后兼容**
  - `snapshot_every_ticks=0` → 不写 snapshot，退化到 run-resilience 老行为
  - `MultiDayRunner` 旧无参构造默认开 snapshot（N=24）+ WAL；不希望就显式
    传 0/False
  - `--resume` 没传 `--resume-strategy` 时等效于 `auto`——优先 snapshot，
    fallback partial（既有 run-resilience 行为）
- **前置依赖**：`run-resilience` 已 archive（partial + `--resume` +
  HotfixSignalHandler 是直接前提）
- **下游依赖**：D3 / 后续 publishable run 可用 `snapshot-only` strategy
  获得"任何中断 ≤ 1 小时模拟时间损失" 的保证

## Non-goals

- **不**做 LLM response cache（让 replay 完全 deterministic）——超出 scope；
  replay 在 LLM 路径上的 drift 接受为已知折扣
- **不**改 Atlas（只读、不变）
- **不**做 cross-machine snapshot 同步（单机内即可）
- **不**改 metric / fitness 报告格式
- **不**自动选 `snapshot_every_ticks`（项目策略 / 文档负责）
- **不**做 incremental / diff snapshot（首版全量；优化留给后续）
- **不**改 run-resilience 既有 SHALL 条款（per-day partial 仍 SHALL 写）
