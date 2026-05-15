# Tasks — tick-level-resume

为长跑提供 tick-level crash recovery：完整 in-memory state 序列化与还原 +
per-tick WAL + per-N-tick snapshot + resume-strategy CLI + suspected_stuck 探活。

**Chain-Position**: `infrastructure`（与 multi-day-simulation / run-resilience
同位；不引入新主边界）

**前置**：`run-resilience` 已 archive（partial + HotfixSignalHandler + `--resume`
是直接基础）
**下游**：D3 / 后续 publishable run 可获得 "任何中断 ≤ 1 snapshot interval
损失" 的保证

## 1. SimulationCheckpoint 数据模型

- [x] 1.1 新建 `synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py`：
  - `SimulationCheckpoint` Pydantic frozen 模型，所有字段按 spec 定义
  - `write_atomic(path)` / `read(path)` / `model_dump()`
  - `_prune_snapshots(output_dir, seed, keep=K)` helper
- [x] 1.2 新增 `SnapshotPolicy` Pydantic frozen + `from_env()` classmethod
- [x] 1.3 单测 `tests/test_simulation_checkpoint.py`：
  - 字段完整性 + frozen 行为
  - `write_atomic` + `read` round-trip
  - 不兼容 schema_version raise IncompatibleCheckpointError
  - `_prune_snapshots` 保留最近 K
  - `SnapshotPolicy.from_env` 默认 + env 覆盖 + 无效值降级

## 2. RNG state 序列化模块

- [x] 2.1 在 `state_snapshot.py` 加：
  - `capture_rng(named: dict[str, random.Random]) -> dict[str, list]` —
    每个 Random 调 getstate() (state 是 tuple → 转 list 保 JSON-safe)
  - `restore_rng(state: dict[str, Any], named: dict[str, random.Random])`
    — setstate() 反向操作
  - 文档化哪些第三方 RNG 不被覆盖（numpy / asyncio）
- [x] 2.2 单测 `tests/test_rng_snapshot.py`：
  - capture 后 restore 到新 Random → 下一次 random() byte-equal
  - 缺失 key warn 但不抛
  - tuple ↔ list 序列化 round-trip

## 3. Ledger to/from snapshot

- [x] 3.1 `synthetic_socio_wind_tunnel/ledger/service.py::Ledger`：
  - `to_snapshot_state() -> dict` 输出 entity_states + item_states +
    door_states + door usage history（全部 Pydantic model_dump）
  - `from_snapshot_state(state)` 清空 in-memory + 校验关键字段 + 反序列化
- [x] 3.2 单测 `tests/test_ledger_snapshot.py` round-trip + 缺字段 raise

## 4. AgentRuntime to/from snapshot

- [x] 4.1 `synthetic_socio_wind_tunnel/agent/runtime.py::AgentRuntime`：
  - `to_snapshot_state()` 输出 current_location / current_plan /
    current_intent / emotional_state / current_tick_in_plan / movement_state
  - `from_snapshot_state(state)`，校验 profile.agent_id 必须匹配
- [x] 4.2 单测：跑 plan 几步 → state → 新 agent restore → state 一致

## 5. MemoryService / MemoryStore to/from snapshot

- [x] 5.1 `synthetic_socio_wind_tunnel/memory/service.py::MemoryService.
  to_snapshot_state()`：包装内部 MemoryStore 序列化（events /
  daily_summaries / reflections / per-agent identity / embeddings cache 元数据）
- [x] 5.2 `from_snapshot_state(state)` 清空 + 反序列化 MemoryStore
- [x] 5.3 单测：累积 events + 1 个 daily_summary → state → new MemoryService
  restore → query 数一致
- [x] 5.4 **P0 灰度**：实测 1000-agent × 14d MemoryStore dump 字节数；若
  > 200 MB 触发剪枝策略（仅 dump 最近 7d events）写进 spec & 实现

## 6. AttentionService to/from snapshot

- [x] 6.1 `synthetic_socio_wind_tunnel/attention/service.py::AttentionService`：
  - `to_snapshot_state()` 输出 pending / consumed notifications + decay state
  - `from_snapshot_state(state)`
- [x] 6.2 单测 round-trip + 缺字段 raise

## 7. SimulationCheckpoint.restore_into 编排

- [x] 7.1 在 state_snapshot.py 实现 `restore_into(*, orchestrator, ledger,
  agents, memory_service, attention_service)`：按 spec 顺序 ledger → agents
  → memory → attention → rng；处理 None 子系统的 skip 逻辑
- [x] 7.2 单测 `tests/test_checkpoint_restore_into.py`：
  - 完整子系统都给定 → 各 to_state 等价
  - memory/attention=None 时跳过且不抛
  - 缺失 agent 抛 ValueError
  - restore 中途子系统抛 → 异常直接传播

## 8. MultiDayRunner 接入 snapshot/wal/restore_from

- [x] 8.1 `multi_day.py::MultiDayRunner.__init__` 新增 3 个参数（按 multi-day-run
  delta 定义）+ `snapshot_policy: SnapshotPolicy | None` 注入路径
- [x] 8.2 主循环：每 tick `on_tick_end` 之后增加 WAL append + 视频率
  snapshot 写盘；保持既有 graceful-stop check 在 snapshot 写盘 **之后**
  发生（让 final snapshot 落地）
- [x] 8.3 主循环启动时若 `restore_from` 非空：先 `restore_into(...)`、
  从 `restore_from.day_index, tick_index+1` 起；`resume_from` 同时给出
  时优先 `restore_from` 并 log warning
- [x] 8.4 写盘失败（WAL 或 snapshot）log warning 但不阻断 run
- [x] 8.5 `tick_index_global` 计算：`day_index * ticks_per_day + tick_index`
  （ticks_per_day 从 orchestrator 拿）

## 9. MultiDayRunner 测试扩展

- [x] 9.1 扩展 `tests/test_multi_day.py`：
  - `test_wal_lines_count_equals_total_ticks`（14d → 4032 行）
  - `test_snapshot_every_24_keeps_last_2`
  - `test_snapshot_zero_disables`（向后兼容）
  - `test_wal_disabled_skips_file`
  - `test_graceful_stop_writes_final_snapshot_regardless_of_N`
  - `test_restore_from_continues_from_next_tick`
  - `test_restore_from_overrides_resume_from`
  - `test_write_failure_logs_but_continues_run`

## 10. End-to-end resume 测试

- [x] 10.1 新建 `tests/test_resume_from_snapshot.py`：
  - `test_round_trip_pause_resume_equivalent`（跑 3 day → 中途 snapshot
    → kill → 用 snapshot 新 runner 继续 → 最终 state 与不中断时**等价**
    on stub provider；LLM 路径不要求 byte-equal）
  - `test_resume_state_no_seam`：restore 后 agent 位置 / memory 数 / ledger
    entity 与中断前一致

## 11. tools/run_variant_suite.py 集成 --resume-strategy

- [x] 11.1 argparse 加 `--resume-strategy` choices=[auto, snapshot-only,
  partial-only, none]、默认 auto；与 `--resume` 互斥校验
- [x] 11.2 实现 auto 路径：
  - 扫 variant_dir 找最近 `seed_{N}_tick*.snapshot.json` →
    `SimulationCheckpoint.read` → 传 `restore_from`
  - 找不到 snapshot 时降级到 partial → resume_from = day+1
  - 都找不到从 day 0
- [x] 11.3 snapshot-only 无 snapshot 时 sys.exit(1) + stderr 提示
- [x] 11.4 partial-only 走 run-resilience 老路径（已有，无改动）
- [x] 11.5 none 强制 fresh start（覆盖既有 `--resume`）
- [x] 11.6 publishable 模式（agents==1000 + num_days==14）默认 auto；none
  仍生效但 stderr 警告

## 12. tools/run_variant_suite.py 集成测试

- [x] 12.1 新建 `tests/test_run_variant_suite_resume_strategy.py`：
  - 4 个 strategy 行为各 1 个 test（subprocess + 制造 fixture 文件）
  - `--resume + --resume-strategy=none` 冲突 fail-fast
  - publishable 模式默认 auto

## 13. tools/audit_run_health.py 新增 suspected_stuck

- [x] 13.1 `HealthAudit.audit(...)` 读 `<run_dir>/<variant>/seed_*.wal.jsonl`
  最后一行 wall_clock；按 `stuck_warn_factor` / `stuck_deadlock_factor`
  阈值判定 rising_wal_silence / suspected_stuck reasons
- [x] 13.2 `suspected_stuck` 进 `_DEADLOCK_REASONS` frozenset；触发 overall
  status `suspected_deadlock`
- [x] 13.3 新建 `tests/test_audit_suspected_stuck.py`：
  - mock WAL 10 min 无新行 → suspected_stuck
  - WAL 3 sec 内新行 → 健康
  - WAL 不存在 → 不标 stuck（与 WAL disabled 模式兼容）
- [x] 13.4 `audit_run_health.py` CLI 输出加 "stuck" 标识 + recommend
  `kill -USR1 + --resume-strategy=snapshot-only` 流程

## 14. 公共 API re-export

- [x] 14.1 `synthetic_socio_wind_tunnel/run_resilience/__init__.py` re-export
  `SimulationCheckpoint` / `SnapshotPolicy`
- [x] 14.2 顶层 `synthetic_socio_wind_tunnel/__init__.py` 同步 re-export
- [x] 14.3 smoke：`from synthetic_socio_wind_tunnel import SimulationCheckpoint`
  成功

## 15. Fitness-audit 探针

- [x] 15.1 新建 `synthetic_socio_wind_tunnel/fitness/audits/tick_level_resume.py`
  含 6 个探针（module / roundtrip / 4 个 subsys）
- [x] 15.2 接入 fitness/audit.py + fitness/audits/__init__.py
- [x] 15.3 跑 `make fitness-audit`，确认 `phase2-gaps.tick-level-resume.*`
  全 PASS

## 16. 文档与配置

- [x] 16.1 新建 `docs/agent_system/16-tick-level-resume.md`：
  - 故事化背景（run-resilience 留下的两个缺口）
  - 架构图：tick → WAL（每 tick）→ SimulationCheckpoint（每 N tick）→
    keep K → resume_into 各子系统
  - CLI 用法：`--resume-strategy` 4 个值
  - 与 run-resilience / multi-day-run 的层级关系
  - replay-drift 接受声明
- [x] 16.2 `.env.example` 增加：
  - `RESILIENCE_SNAPSHOT_EVERY_TICKS=24`
  - `RESILIENCE_SNAPSHOT_KEEP_LAST=2`
  - `RESILIENCE_WAL_ENABLED=1`
  - `RESILIENCE_WAL_FSYNC_EVERY_TICKS=1`
  - `RESILIENCE_HEALTH_TICK_SECONDS_EXPECTED=5`
  注释说明默认值与权衡
- [x] 16.3 `CLAUDE.md` "关键不变量" 加一条 `tick-level-resume 2026-05-16`：
  - publishable run SHALL 启用 snapshot（every_ticks=24 默认）+ WAL
  - 新增子系统 mutable state 字段时必须 update 对应 `to_snapshot_state`/
    `from_snapshot_state` 方法
  - 任何中断损失 ≤ `every_ticks * tick_minutes` simulated time
- [x] 16.4 README "Development Status" 加一行 `tick-level-resume`

## 17. 性能 & 体积验证

- [x] 17.1 perf test `tests/test_snapshot_perf.py`：
  - 100 agent × 3 day × `snapshot_every_ticks=24, wal_enabled=True` vs
    `=0, =False` 两配置；wall time delta ≤ 10%
- [x] 17.2 disk test `tests/test_snapshot_disk_budget.py`：
  - 模拟 1000 agent × 14 day fixture（或 100 agent × 14 day scaled-down）：
    snapshot 目录 size ≤ 200 MB
- [x] 17.3 真灰度（手动）：跑一次 100-agent × 3-day × DeepSeek 真 LLM 跑，
  对比 partial-only vs auto strategy 的 wall time + disk + resume 行为；
  把结果写进 ship doc

## 18. 验证 & 归档准备

- [x] 18.1 `openspec validate tick-level-resume --strict` 通过
- [x] 18.2 grep 一致性检查：`SimulationCheckpoint` / `SnapshotPolicy` /
  `snapshot_every_ticks` 在 spec / 代码 / 测试三处名字一致
- [x] 18.3 grep RESILIENCE_SNAPSHOT_* / RESILIENCE_WAL_* env vars 三处一致
  （spec 表格 / .env.example / from_env 实现）
- [x] 18.4 所有 ADDED Requirement 至少一个 Scenario 有对应 test
- [x] 18.5 准备 `docs/sessions/2026-MM-DD-tick-level-resume-shipped.md` ship doc
