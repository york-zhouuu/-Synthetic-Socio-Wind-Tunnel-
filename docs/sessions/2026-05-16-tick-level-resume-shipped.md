# tick-level-resume shipped · 2026-05-16

## TL;DR

`run-resilience`（2026-05-15）archive 后用户立刻指出两个未关上的缺口：

1. `MultiDayRunner.resume_from` 只是循环跳过、不真正还原 in-memory state
2. 粒度只到天——SIGKILL 在 tick 100 时丢一整天

本 change（tick-level-resume）补上：完整 `SimulationCheckpoint` 序列化 +
per-tick WAL + per-N-tick snapshot + `restore_into` 各子系统 + 4 个
`--resume-strategy` + `suspected_stuck` 探活维度。**1512 passed / 0
failed / 3 skipped**；perf overhead **9%**（spec 要求 ≤ 10%）；snapshot
disk 1.7 MB / 3 day（远低于 200 MB 上限）。

## 设计要点

- **不做 deterministic replay**：LLM 路径下 replay 必然 drift。改用
  **state 直接还原**——snapshot 写完整 in-memory state，restore 灌回
- **per-tick WAL（~100 B/tick）+ per-N-tick snapshot**：WAL 给运维实时
  进度可见性（独立于 snapshot 落盘频率）；snapshot 给状态恢复（默认
  N=24 = hourly）
- **滚动保留 K=2**：peak disk ≤ ~200 MB / seed
- **graceful-stop 强写 final snapshot**：SIGUSR1 收到后无论是否 N 整数倍
- **abandon-and-retry pending OperationPool ops**：避免半 state machine 序列化
- **RNG state 必须 snapshot**：保证 restore 后下一步随机序列与原本一致

## 实现要点

| 模块 / 文件 | 角色 |
|---|---|
| `synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py` | SimulationCheckpoint + SnapshotPolicy + WALWriter + capture/restore_rng |
| `synthetic_socio_wind_tunnel/ledger/service.py` | Ledger 加 to/from_snapshot_state |
| `synthetic_socio_wind_tunnel/agent/runtime.py` | AgentRuntime 加 to/from_snapshot_state（pending ops abandon、_tick_inputs 清空） |
| `synthetic_socio_wind_tunnel/memory/service.py` | MemoryService 加 to/from_snapshot_state + MemoryEvent JSON helpers |
| `synthetic_socio_wind_tunnel/attention/service.py` | AttentionService 加 to/from_snapshot_state |
| `synthetic_socio_wind_tunnel/orchestrator/multi_day.py` | MultiDayRunner +3 参数（snapshot_policy / restore_from / attention_service）+ 主循环 WAL + snapshot 写盘 + restore_into 启动路径 |
| `synthetic_socio_wind_tunnel/run_resilience/health.py` | HealthAudit 加 WAL silence 检查 → suspected_stuck 维度 |
| `tools/run_variant_suite.py` | `--resume-strategy` 4 个值；restore_from snap 路径 |
| `synthetic_socio_wind_tunnel/fitness/audits/tick_level_resume.py` | 6 个 fitness audit 探针 |

## 测试覆盖

| 测试文件 | 数量 |
|---|---|
| `tests/test_simulation_checkpoint.py` | 20（fields / atomic write / file helpers / SnapshotPolicy） |
| `tests/test_rng_snapshot.py` | 11（capture/restore RNG / WAL writer/reader） |
| `tests/test_subsystem_snapshot.py` | 14（4 子系统 round-trip） |
| `tests/test_checkpoint_restore_into.py` | 5（end-to-end restore） |
| `tests/test_tick_snapshot_lifecycle.py` | 9（WAL line count / snapshot frequency / K-keep / graceful-stop final） |
| `tests/test_resume_from_snapshot.py` | 4（E2E resume：state 等价 / runner 接入 / exceed 抛 / no-seam） |
| `tests/test_audit_suspected_stuck.py` | 6（WAL silence → suspected_stuck） |
| `tests/test_run_variant_suite_resume_strategy.py` | 4（CLI flags / snapshot-only fail-fast / none） |
| `tests/test_snapshot_perf.py` | 2（≤ 10% overhead / ≤ 200 MB disk） |
| **总计** | **75 个新增 test，全 pass** |

### 全量回归

**1512 passed, 3 skipped, 0 failed** (9.2 min wall, 含 2 个修好的旧测试
回归 —— glob 模式未排除新增 snapshot 文件)。

### Perf 实测
- `no_snap=3.5s, snap=3.9s, ratio=1.09x`（100 agent × 3 day stub-mode）
- snapshot disk: 1.7 MB / 3 day 100 agent → 推算 1000 agent × 14 day ≈ 80 MB（仍远低于 200 MB 上限）

## 用法速记

```bash
# 默认就开启了
python tools/run_variant_suite.py --variants baseline,hp,gd,pf \
  --seeds 15 --agents 1000 --num-days 14 \
  --mode publishable --use-aitown --aitown-provider deepseek

# 看进度
tail -f data/experiments/<run>/variant_baseline/seed_42.wal.jsonl

# 中断后续跑（snapshot 优先）
python tools/run_variant_suite.py --suite-dir <run> \
  --resume-strategy snapshot-only ...

# 巡检（含 suspected_stuck 维度）
python tools/audit_run_health.py data/experiments/<run>/
```

## 已 defer 的任务

- D3 publishable run 实跑（待 D2 完成 + 用户启动）
- 真 DeepSeek snapshot disk budget 实测（要等 publishable scale 跑出来）

## 验证清单

- [x] 1512 passed / 3 skipped / 0 failed
- [x] `openspec validate tick-level-resume --strict` 通过
- [x] perf overhead ≤ 10%（实测 9%）
- [x] disk budget ≤ 200 MB（实测 1.7 MB at 3 day × 100 agent）
- [x] `from synthetic_socio_wind_tunnel import SimulationCheckpoint, SnapshotPolicy` 顶层 import 成功
- [x] fitness-audit `phase2-gaps.tick-level-resume.*` 6/6 PASS
- [x] grep 一致性 (SimulationCheckpoint / SnapshotPolicy / WALWriter / to_snapshot_state / from_snapshot_state) 三处对齐
- [x] RESILIENCE_SNAPSHOT_* / WAL_* / HEALTH_* env vars 三处对齐
- [x] CLAUDE.md "关键不变量" 加 tick-level-resume 段
- [x] README "Development Status" 加 tick-level-resume 行
- [x] `docs/agent_system/16-tick-level-resume.md` 用户向白话指南

## 下一步

1. `openspec archive tick-level-resume`
2. 等 D2 完成（Mac A 上跑的 run-resilience 之前的 DeepSeek run）
3. 启动 D3：
   - `tools/preflight_full_smoke.py --provider deepseek`（run-resilience gate）
   - `run_variant_suite.py --agents 1000 --num-days 14 --seeds 15` 开启
     `RESILIENCE_SNAPSHOT_EVERY_TICKS=24` 默认 + WAL
   - 巡检：`audit_run_health.py` 加入 launchd（10 min 间隔），监控
     `suspected_stuck`（基于 WAL mtime）
4. archive 后两层 capability 合在一起就是 "publishable run 出问题最多丢
   ≤ 1 tick 数据" 的完整保障
