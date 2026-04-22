# Multi-day Simulation

> 14 天 protocol 的基建层。本文档补充
> [`13-research-design.md`](13-research-design.md) Part III 的实验协议——
> 协议的"执行能力"住在这里。

由 `openspec/changes/archive/2026-04-22-multi-day-simulation/` 实现。
正式 spec：`openspec/specs/multi-day-run/spec.md`（主能力）+ 三个 MODIFIED
spec（`orchestrator` / `memory` / `agent`）。

---

## 分层

```
┌────────────────────────────────────────────────────────────────┐
│  MultiDayRunner   一次 run = N 天                               │
│  (multi_day.py)                                                 │
│    ├── on_day_start(date, day_index)    （调用方自选逻辑）      │
│    ├── orchestrator.run(day_index=i, simulated_date=d)          │
│    │     ├── on_simulation_start                               │
│    │     ├── 288 tick × { on_tick_start → step → resolve →     │
│    │     │                 commit → encounter → on_tick_end }   │
│    │     └── on_simulation_end                                 │
│    ├── memory.run_daily_summary（若接入）                        │
│    └── on_day_end(date, day_index, summary_batch)               │
└────────────────────────────────────────────────────────────────┘
```

**职责分工**：
- `Orchestrator`：1 天的 288 tick 循环 + hook（无跨日感知）
- `MultiDayRunner`：N 天调度 + day hook + memory/planner 自动接入

---

## 关键数据字段

所有单日数据结构增加 `day_index: int = 0` 与
`simulated_date: date | None = None`（单日调用保持默认）：

| 类 | 新字段 |
|---|---|
| `TickContext` | `simulated_date` / `day_index` |
| `TickResult` | 同上 |
| `CommitRecord` | 同上 |
| `SimulationContext` | 同上 |
| `SimulationSummary` | 同上 |
| `MemoryEvent` | `day_index` |

---

## CLI 用法

### 最小 smoke（3 天 × 10 agents × 2 seed，dev 模式）

```bash
python3 tools/run_multi_day_experiment.py \
    --num-days 3 --agents 10 --seeds 2 --mode dev \
    --variant baseline
```

### 14 天 publishable（100 agents × 30 seed，耗时约 10 分钟）

```bash
python3 tools/run_multi_day_experiment.py \
    --start-date 2026-04-22 --num-days 14 \
    --agents 100 --seeds 30 \
    --mode publishable --variant baseline
```

输出：
- `data/runs/<timestamp>_<variant>/seed_<N>.json`（每 seed 一份）
- `data/runs/<timestamp>_<variant>/aggregate.json`（median/IQR/95% CI）

### 与 smoke demo 联动（快速 multi-day 冒烟）

```bash
python3 tools/smoke_experiment_demo.py --agents 30 --multi-day
```

---

## Hook 时序示例

```python
from datetime import date
from synthetic_socio_wind_tunnel.orchestrator import MultiDayRunner, Orchestrator
from synthetic_socio_wind_tunnel.memory import MemoryService

orchestrator = Orchestrator(atlas, ledger, runtimes)
memory = MemoryService()

# memory 接 orchestrator 的 tick 级 hook
orchestrator.register_on_tick_end(
    lambda tr: memory.process_tick(tr, agents_by_id)
)

runner = MultiDayRunner(
    orchestrator=orchestrator,
    memory_service=memory,
    seed=42,
    mode="publishable",
)

# 可选：调用方定义的 phase 切换 / metrics 采集
def on_day_start(d, idx):
    if 4 <= idx < 10:
        # Intervention phase: attach variant-specific feed generator
        ...

def on_day_end(d, idx, batch):
    # batch: dict[agent_id → DailySummary]
    ...

result = runner.run_multi_day(
    start_date=date(2026, 4, 22),
    num_days=14,
    on_day_start=on_day_start,
    on_day_end=on_day_end,
)
```

---

## CarryoverContext（memory → planner 的接口）

`MemoryService.get_carryover_context(agent_id, current_day_index=N)` 返回：

| 字段 | 内容 |
|---|---|
| `yesterday_summary` | day_index=N-1 的 `DailySummary`，若不存在为 `None` |
| `recent_reflections` | day_index ∈ [N-4, N-2] 的摘要，按 day_index 升序 |
| `pending_task_anchors` | `task_received` 事件按 importance 降序 top 5 |

`Planner.generate_daily_plan(..., carryover=ctx)` 把它拼进 prompt：
- **1500 字符 cap**，超限时 `yesterday_summary.summary_text` 被截断到 300 字符 + `…`
- `carryover=None` 时 prompt 与单日路径**完全一致**（向后兼容）

---

## 性能约束（已实测）

| 规模 | 实测 wall time | 规格上限 |
|---|---|---|
| 1 天 × 100 agent × 1 seed | 1.0 s | - |
| 3 天 × 30 agent × 1 seed（--multi-day smoke）| 1.1 s | - |
| 14 天 × 100 agent × 1 seed | 10-18 s | ≤ 30 s ✓ |
| 14 天 × 100 agent × 30 seed（完整 publishable）| ≈ 7 min（估）| ≤ 60 min |

---

## 两档 mode

| mode | num_days 上限 | 用途 |
|---|---|---|
| `dev` | 3 | 代码迭代、smoke、快速验证 |
| `publishable` | 无上限 | 交付 / 答辩 / 投稿 |

Dev mode 结果 **MUST NOT** 出现在 publishable report；MultiDayRunner 在
dev 模式下对 > 3 天请求直接 `ValueError` 拒绝。

---

## 与 research-design 的对应

| `13-research-design.md` Part III | 本 change 提供 |
|---|---|
| 14-day Baseline/Intervention/Post | `MultiDayRunner.run_multi_day(num_days=14)` |
| Phase 切换由 day_index | 调用方在 `on_day_start` 里按 day_index 分支 |
| β 严谨度 30 seeds | 调用方外层循环 seed → `MultiDayResult.combine(...)` |
| Cross-seed 聚合 | `MultiDayAggregate` median/IQR/95% CI |

---

## 已知局限（未来 change）

- 无 checkpointing（14 天 < 30s，暂不需要）
- `CarryoverContext.pending_task_anchors` 的 "completed" 检测靠 importance；
  真正的任务完成状态机是 `conversation` / `policy-hack` 的事
- `MultiDayResult.metadata` 预留给 `metrics` change 填充实验指标
- Cross-model 一致性（Haiku vs Sonnet 同 scenario）属于 `validation-strategy`
  的 scope，不在本 change
