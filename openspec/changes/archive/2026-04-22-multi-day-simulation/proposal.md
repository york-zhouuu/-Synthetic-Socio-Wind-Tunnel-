## Why

`research-design` change 冻结了 14 天 × 30 seed 的实验协议。但当前基建是
**单日循环**：

- `Orchestrator.run()` 跑 288 tick 一天、跑完即止
- `MemoryService.run_daily_summary()` 已实现但**从未被读**——单日 scope 下
  summary 写完就没人看；memory 基建对实际实验的贡献 ≈ 0
- `Planner.generate_daily_plan()` 每日只看 `AgentProfile`，不看昨日经历
- `simulated_time` 只在一天内推进，无跨天语义
- 没有任何 cross-day outcome 聚合机制

后果：
- 所有 `research-design` 的 14 天协议 MUST 先跑**14 次独立单日**再手动拼接
  —— agent 第 N 天不知道第 N-1 天发生了什么，habit formation 测不出
- Memory 能力变成 **dead code**——已花成本实现、但对 thesis 没贡献
- 整个 `research-design` 的 publishable experiment **无法真正执行**——这是
  当前 critical path blocker

本 change 做**基建迭代**，把单日循环扩为 N 日循环，同时把已实现的 memory
接入次日 planner，闭环 "经历 → 总结 → 反思 → 次日计划" 的叙事 loop。
本 change 完成后，`research-design` 的实验协议可以真正跑起来。

**Chain-Position**：`infrastructure`（跨 4 层；为所有实验提供时间维度）。

## What Changes

### 1. Orchestrator 多日 run loop（MODIFIED）

新增 `Orchestrator.run_multi_day(start_date, num_days)` 公共 API：
- 调用 `run()` 作为 per-day sub-routine
- 按天 roll-over：day 结束时触发 `on_day_end` hook（跑 daily summary、
  reset AttentionService 的一次性状态）；次日开始前触发 `on_day_start` hook
  （生成新 daily plan、读昨日 summary）
- 统一 `TickContext` 增加 `simulated_date: date` 与 `day_index: int` 字段

现有 `run()` 保持行为不变（单日兼容路径）。

### 2. Memory 跨日 carryover（MODIFIED）

`MemoryService` 新增：
- `get_recent_daily_summaries(agent_id, last_n_days) -> list[DailySummary]`
- `get_carryover_context(agent_id, current_date) -> CarryoverContext`（供
  planner prompt 拼装——包含 `yesterday_summary` / `recent_reflections` /
  `pending_task_anchors`）

`DailySummary` 从 "写完就完" 升级为**次日 planner 的必读输入**。

### 3. Planner 跨日 prompt（MODIFIED）

`Planner.generate_daily_plan(profile, date, carryover=None)` 新增
`carryover: CarryoverContext | None` 参数：
- carryover=None 时行为不变（第 0 天、或 baseline 不读历史时）
- carryover 非空时，prompt 插入 "昨日 summary" 与 "近 3 日反思" 段落，
  指示 LLM 生成**与历史一致但允许偏离**的新 plan

### 4. Date 语义（MODIFIED）

- `TickResult` / `TickContext` / `CommitRecord` 新增 `simulated_date: date`
  字段（派生自 `simulated_time.date()`）
- `MemoryEvent.simulated_time` 已有；新增 `MemoryEvent.day_index: int`
  （相对 run 起始日的偏移）
- Ledger 不动（仍记录 wall-clock-ish 时间戳，无需跨天语义）

### 5. 多日实验 runner（NEW capability）

新能力 `multi-day-run` 的 spec：
- 协议化 Baseline / Intervention / Post phase 切换（按 day_index 触发）
- 统一 cross-seed 聚合接口（给 `metrics` change 后续实现指标采集
  预留 hook）
- 命令行入口 `tools/run_multi_day_experiment.py`（非核心包，demo 位置）
- 暴露最小 publishable-mode（30 seed × 14 day）与 dev-mode（3 seed × 3 day）
  两档开关，对齐 `research-design` spec

### 6. 性能约束

- 14 天 × 100 agent 单 seed run SHALL 在 < 30s（wall time）内完成
  （smoke demo 基线：1 天 = 1.2s；14 × 1.2 = 16.8s 预期，留 2× 余量）
- 30 seed × 4 variant × 14 day 全 suite SHALL 在 < 60min（wall time）内完成
  （约 30 × 4 × 17s = 34min 预期）

## Capabilities

### New Capabilities

- `multi-day-run`: 多日实验 runner，负责 day-by-day 调度、phase 切换、
  cross-seed 聚合接口。与 `orchestrator`（单日 tick 循环）分层明确：
  orchestrator 负责 1 天内的 tick，multi-day-run 负责 N 天的 orchestration。

### Modified Capabilities

- `orchestrator`: 新增 `run_multi_day()` 与 `on_day_start` / `on_day_end`
  hook；`TickContext` / `TickResult` 新增 `simulated_date` / `day_index`
  字段
- `memory`: 新增 `get_carryover_context()` 方法；`DailySummary` 从输出升级
  为输入；`MemoryEvent` 新增 `day_index` 字段
- `agent`: `Planner.generate_daily_plan` 新增 `carryover` 参数；prompt
  模板对应扩展；`AgentRuntime.plan` 每日重新生成的触发条件由 `day_index`
  推进

## Impact

- **新代码**：
  - `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`（新文件，
    提供 `Orchestrator.run_multi_day` 与相关 hook）
  - `synthetic_socio_wind_tunnel/memory/carryover.py`（新文件，
    `CarryoverContext` / `get_carryover_context`）
  - `tools/run_multi_day_experiment.py`（新 demo 入口，类似 smoke_demo
    但按 14 天 × 30 seed）
- **修改**：
  - `synthetic_socio_wind_tunnel/orchestrator/models.py`（`TickContext` +
    `TickResult` 加字段）
  - `synthetic_socio_wind_tunnel/agent/planner.py`（`generate_daily_plan`
    加 carryover 参数）
  - `synthetic_socio_wind_tunnel/memory/service.py`（新增 carryover 方法）
  - `synthetic_socio_wind_tunnel/memory/models.py`（`MemoryEvent` 加
    `day_index`）
  - 公共 API re-export（`synthetic_socio_wind_tunnel/__init__.py`）
- **测试**：
  - `tests/test_multi_day.py`（新文件，覆盖 run_multi_day + carryover +
    phase 切换）
  - `tests/test_memory.py`（扩展：daily_summary → next day planner 的集成）
- **前置依赖**：无（独立基建 change）
- **下游依赖**：`research-design` 的实验协议依赖本 change 完成；`metrics`
  能力依赖本 change 提供的 cross-day outcome hook
- **向后兼容**：`Orchestrator.run()` 保持不变；旧单日调用方零改动；现有
  smoke demo 脚本不动仍能跑
