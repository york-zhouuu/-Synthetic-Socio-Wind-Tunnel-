# Tasks — multi-day-simulation

基建 iteration：把单日循环扩为 N 日循环，把 memory daily_summary 接入次日
planner。代码改动集中在 orchestrator / memory / agent 三处。

**Chain-Position**: `infrastructure`（为所有实验提供时间维度；不引入新边界）

**前置**：无（独立基建 change）
**下游**：`research-design` 的实验协议依赖本 change；`metrics` 的指标
采集依赖本 change 的 MultiDayResult

## 1. Data model 扩展

- [x] 1.1 `synthetic_socio_wind_tunnel/orchestrator/models.py`：在
  `TickContext` / `TickResult` / `CommitRecord` / `SimulationSummary`
  新增 `simulated_date: date` 与 `day_index: int = 0` 字段；frozen 约束不变
- [x] 1.2 `synthetic_socio_wind_tunnel/memory/models.py`：`MemoryEvent`
  新增 `day_index: int = 0` 字段
- [x] 1.3 新建 `synthetic_socio_wind_tunnel/memory/carryover.py`：定义
  `CarryoverContext` Pydantic frozen 模型（字段见 spec）

## 2. MultiDayRunner 核心

- [x] 2.1 新建 `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`：
  - `MultiDayRunner` 类 + 构造参数
  - `run_multi_day(start_date, num_days, on_day_start, on_day_end)`
  - `MultiDayResult` / `DayRunSummary` / `MultiDayAggregate` 数据类
  - `MultiDayResult.combine(list)` classmethod 计算 median/IQR/95%CI
  - `mode="dev" | "publishable"` 开关（dev 限 3 天）
- [x] 2.2 让 `MultiDayRunner` 自动 wire：若 memory_service 传入，每 day 末
  调 `run_daily_summary`；若 planner 传入，每 day 初生成 plan 并把
  carryover 注入

## 3. Orchestrator 多日参数

- [x] 3.1 `orchestrator/service.py::Orchestrator.run` 签名加
  `*, day_index: int = 0, simulated_date: date | None = None` kwarg
- [x] 3.1a 内部把 `day_index` / `simulated_date` 填入所有
  TickContext / TickResult / CommitRecord
- [x] 3.2 **向后兼容验证**：所有现有 `Orchestrator.run()` 无参调用 SHALL
  继续工作，day_index=0 / simulated_date 从 Ledger.current_time 派生

## 4. Memory 跨日接口

- [x] 4.1 `memory/service.py`：
  - `get_daily_summary(agent_id, day_index) -> DailySummary | None`
  - `get_recent_daily_summaries(agent_id, *, last_n_days=3, ref_day_index=None)`
  - `get_carryover_context(agent_id, *, current_day_index)`
- [x] 4.2 `memory/service.py::process_tick`：把 `tick_result.day_index`
  传递给派生的所有 MemoryEvent
- [x] 4.3 `run_daily_summary` 产出的 `daily_summary` 事件写入
  `MemoryStore` 时 day_index 必须正确填充

## 5. Planner 跨日 prompt

- [x] 5.1 `agent/planner.py::generate_daily_plan` 签名加 `carryover:
  CarryoverContext | None = None` kwarg
- [x] 5.2 `_PLAN_PROMPT_TEMPLATE` 扩展为两段：原 prompt + 可选 carryover
  段（若 carryover=None 则省略整段；行为与单日完全一致）
- [x] 5.3 Prompt 构造时实现 1500 字符 cap + summary_text 300 字符截断
  （见 spec Scenario）

## 6. CLI 入口

- [x] 6.1 新建 `tools/run_multi_day_experiment.py`：
  - argparse: `--start-date / --num-days / --agents / --seeds /
    --variant / --mode`
  - 循环 seed → 跑 MultiDayRunner → dump JSON
  - aggregate 调 `MultiDayResult.combine`
- [x] 6.2 在 `tools/smoke_experiment_demo.py` 中加 `--multi-day` 开关，
  触发多日路径（默认仍跑单日，保持向后兼容）

## 7. 公共 API re-export

- [x] 7.1 `synthetic_socio_wind_tunnel/__init__.py` 导出：
  - `MultiDayRunner` / `MultiDayResult` / `MultiDayAggregate`
  - `CarryoverContext`
- [x] 7.2 `synthetic_socio_wind_tunnel/orchestrator/__init__.py` 同步
- [x] 7.3 `synthetic_socio_wind_tunnel/memory/__init__.py` 导出
  `CarryoverContext` 与新方法

## 8. 测试

- [x] 8.1 新建 `tests/test_multi_day.py`：
  - `test_multi_day_runner_construct`
  - `test_run_multi_day_3days_2agents`
  - `test_on_day_start_end_hooks_order`
  - `test_day_index_propagates_to_tick_result`
  - `test_day_index_propagates_to_memory_event`
  - `test_dev_mode_rejects_14_days`
  - `test_publishable_mode_allows_14_days`
  - `test_14_day_100_agent_performance`（wall time ≤ 30s）
- [x] 8.2 新建 `tests/test_carryover.py`：
  - `test_carryover_day_0_empty`
  - `test_carryover_day_5_full`
  - `test_get_recent_daily_summaries_3_day_window`
  - `test_pending_task_anchors_max_5`
- [x] 8.3 扩展 `tests/test_orchestrator.py`：
  - `test_run_single_day_backward_compat`（day_index=0 默认行为不变）
  - `test_run_with_explicit_day_index`
- [x] 8.4 扩展 `tests/test_agent_phase1.py` 或新建
  `tests/test_planner_carryover.py`：
  - `test_generate_daily_plan_without_carryover_unchanged`
  - `test_generate_daily_plan_with_carryover_adds_sections`
  - `test_carryover_truncation_at_1500_chars`
- [x] 8.5 扩展 `tests/test_memory.py`：
  - `test_daily_summary_indexed_by_day_index`
  - `test_process_tick_propagates_day_index`

## 9. Fitness-audit 扩展

- [x] 9.1 `synthetic_socio_wind_tunnel/fitness/audits/phase2_gaps.py`：
  新增 `phase2-gaps.multi-day-run` 探针（`_module_exists` 模式），
  mitigation_change = `multi-day-simulation`
- [x] 9.2 跑 `make fitness-audit`，确认该条从 fail → pass

## 10. 文档与示例

- [x] 10.1 新建 `docs/agent_system/14-multi-day-simulation.md`：
  - 架构简图（Orchestrator vs MultiDayRunner 分层）
  - CLI 用法示例
  - Hook 时序图（on_day_start → orchestrator.run → run_daily_summary →
    on_day_end）
  - 与 `experimental-design` spec 的对应
- [x] 10.2 更新 `README.md` 的 Development Status 表：为 `orchestrator` 行
  补一条"多日扩展（multi-day-simulation）"状态
- [x] 10.3 更新 `docs/agent_system/08-orchestrator-tick-loop.md`：加一个
  "多日调用" 附录章节

## 11. 性能 & 回归

- [x] 11.1 运行全部 `pytest tests/`，确认单日路径 0 回归
- [x] 11.2 运行 `tools/smoke_experiment_demo.py --agents 100`（不带
  --multi-day）：8/8 PASS 输出不变
- [x] 11.3 运行 `tools/smoke_experiment_demo.py --agents 100 --multi-day`
  （新开关）：确认多日路径可跑通，wall time 报告记入 demo 输出
- [x] 11.4 跑一次 `tools/run_multi_day_experiment.py --num-days 14
  --agents 100 --seeds 5 --mode publishable --variant baseline`，
  确认 wall time ≤ 30s/seed、总 ≤ 3 分钟

## 12. 验证

- [x] 12.1 `openspec validate multi-day-simulation --strict` 通过
- [x] 12.2 grep 检查：`MultiDayRunner` / `CarryoverContext` / `day_index`
  在 spec / 代码 / 测试三处一致
- [x] 12.3 确认所有 MODIFIED Requirement 的 Scenario 新增条目对应代码有
  测试覆盖
