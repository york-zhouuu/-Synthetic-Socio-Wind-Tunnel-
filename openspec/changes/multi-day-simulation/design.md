## Context

当前 Phase 2 已实现：
- `orchestrator`（单日 288 tick 循环 + hook / 冲突裁决 / encounter 检测）
- `memory`（MemoryEvent 流 + 4-way retriever + `run_daily_summary`）
- `agent.Planner.generate_daily_plan`（单日 plan 生成 + replan）
- `attention-channel`（feed 注入 + AttentionState 滤镜）

这些组件**各自工作**，但缺少一根"时间脊柱"——跨天的推进逻辑。smoke demo
验证了单日 pipeline，`research-design` 现要求 14 天协议——此处 pipeline 必须
往上长出一层。

## Goals / Non-Goals

**Goals:**
- 提供**一根**跨天推进的主循环（`run_multi_day`），不让调用方拼接多个
  `run()`
- 让 `DailySummary` 真正进入次日 plan——memory 基建的第一个实用客户
- Decouple "per-day orchestration"（orchestrator）与 "per-run orchestration"
  （multi-day-run）——分层清晰，便于未来独立演进
- 保持向后兼容：smoke demo 单日调用方不动

**Non-Goals:**
- 不实现任何实验 variant（那是 `policy-hack` / 未来实验 change）
- 不实现任何指标采集（那是 `metrics`）
- 不改变 Ledger 的时间语义（Ledger 不需要知道 "第几天"）
- 不做周 / 月级别——14 天协议是当前需求上限
- 不做 persistent state（实验结束 state 全丢，重新跑；持久化是未来 `artifacts`
  change 的事）

## Decisions

### D1：多日 runner 是独立 capability 而非 orchestrator 扩展

**选择**：新 capability `multi-day-run`，与 `orchestrator` 分层（orchestrator
管 1 天、multi-day-run 管 N 天）。

**备选**：
- 把 multi-day 逻辑塞进 orchestrator（让 `Orchestrator.run_multi_day` 就是
  一个方法）
  - 优点：调用方只需认 1 个类
  - 缺点：orchestrator 变成 "一日 + 多日 + phase + seed 聚合" 的大杂烩；
    未来想引入 persistent 多周实验会更难拆
- 独立 capability ✓：分层清晰，orchestrator 继续只管 1 天

**Why 分层**：分层代价是多一个 class（`MultiDayRunner`）与一个新 spec；
收益是 orchestrator 不肥、multi-day-run 可以独立被 `experimental-runner`
类的更高层组件使用（未来若有）。分层成本可承受。

### D2：hook 而非继承

**选择**：`on_day_start` / `on_day_end` 是 `Orchestrator.run_multi_day` 向
调用方暴露的 hook（callable），与现有 `on_tick_start` / `on_tick_end` 同机制。

**备选**：
- 让 memory / planner subclass `Orchestrator`——反模式，CQRS 单源头被破坏
- 让 multi-day 依赖 memory / planner 的硬编码引用——耦合太紧

**Why hook**：hook 是现成模式，multi-day-run 向 memory / planner 传 hook，
orchestrator 只负责触发；memory / planner 不需要知道"我在一个多日 run 里"。

### D3：CarryoverContext 是 pure-data，planner 决定如何用

**选择**：`CarryoverContext` 是一个 Pydantic model（yesterday_summary /
recent_reflections / pending_task_anchors）；planner 把它拼进 prompt 的
具体方式由 planner 自己决定。

**备选**：
- carryover 直接传原始 `list[MemoryEvent]`——不封装
  - 缺点：planner 需要自己重复 retrieval 逻辑
- carryover 渲染好的 markdown block 传给 planner
  - 缺点：违反 CQRS——memory 不应承担 prompt 模板职责

**Why Pydantic model**：结构化数据 memory 侧给；prompt 模板 planner 侧用。
清晰的 CQRS 边界。

### D4：day_index 是 0-based

**选择**：`day_index = 0` 代表 run 的第一天（Baseline day 1）；Baseline
跨 0-3，Intervention 跨 4-9，Post 跨 10-13。

**备选**：1-based（Day 1 = day_index 1）
- 符合日常"第一天"语感
- 但与 tick_index（0-based）不一致；所有 seq 下标都 0-based 是 Python 习惯

**Why 0-based**：与 `tick_index` 一致；code consistency > 人类数数习惯。

### D5：`simulated_date` 存在哪些结构里

**选择**：
- `TickContext.simulated_date`（派生自 `simulated_time.date()`）
- `TickResult.simulated_date`（同）
- `CommitRecord.simulated_date`（同）
- `MemoryEvent.day_index`（不直接存 date——date 容易"绝对化"，day_index
  纯相对便于跨 run 聚合）

**不存**：Ledger 内部（避免 Ledger 知晓多日语义）。

### D6：Phase 切换由 day_index 决定

**选择**：`experimental-runner`（调用 multi-day-run）在 `on_day_start` hook
中根据 day_index 决定是否激活 intervention。orchestrator / multi-day-run
本身不知道 phase 概念。

**备选**：
- 把 phase 语义下沉到 orchestrator——反模式，orchestrator 不该知道研究方法论
- 把 phase 语义写进 multi-day-run spec——同样反模式

**Why 向上推**：phase 是研究方法论关注点，应由调用者（实验 runner / test
/ notebook）决定；multi-day-run 只提供 day tick。

### D7：run_multi_day 的签名

**选择**：
```python
def run_multi_day(
    self,
    *,
    start_date: date,
    num_days: int,
    on_day_start: Callable[[date, int], None] | None = None,
    on_day_end: Callable[[date, int, DailySummaryBatch], None] | None = None,
) -> MultiDayResult: ...
```

**Why 结构化**：
- 必需参数走 kwarg-only，防止位置参数歧义
- `on_day_*` 是 optional callable——调用方自己决定是否 plug in memory / planner
- 返回 `MultiDayResult`（per-day TickSummary list + 跨天聚合数据）

### D8：DailySummary 已在 memory.models；不改

**选择**：复用现有 `DailySummary` 数据类；仅扩展 `get_recent_daily_summaries`
与 `get_carryover_context` 的**读取接口**。

**Why**：DailySummary 结构已稳定；新加方法即可，不破坏现有契约。

### D9：Planner prompt 的 carryover 格式

**选择**：prompt 段落示例（中文）：
```
【昨日经历摘要】
{yesterday_summary.summary_text}

【近 3 日反思】
- day -1: {recent_summaries[-1].summary_text[:120]}
- day -2: ...

【未完成任务锚点】
{pending_task_anchors}
```

**约束**：
- 总字数 upper bound（prompt 防爆炸）：1500 字符
- 若 carryover 过长则 truncate summary_text 至 300 字

## Risks / Trade-offs

**[Risk 1] N-day 运行时间仍可能超预算**
- 预估 14 天 × 100 agent ≈ 17s；但 memory carryover 会增加每日 planner
  LLM 调用耗时（或本地 StubLLM 调用耗时）
→ 缓解：加 integration test 专门测 14 天性能 ≤ 30s；超时 fail

**[Risk 2] 跨日 state 泄漏**
- AttentionService 的 notification queue 若不在 on_day_end 清理，次日会拿到
  昨日残留
→ 缓解：spec 明确 `on_day_end` 必须 reset 一次性 state（notifications already
  delivered、tick-level caches）；pytest 覆盖

**[Risk 3] Planner 在 carryover 过大时 prompt 爆炸**
- 14 天后每日携带 14 份 summary 风险膨胀
→ 缓解：D9 的 upper bound + `get_carryover_context` 默认只返 last 3 days

**[Risk 4] 测试运行时间**
- 14 天 × N seed 集成测试 CI 不跑得动
→ 缓解：集成 test 只跑 3 天 × 1 seed（~5s）；publishable 14×30 只在本地 /
专门环境跑

**[Risk 5] 现有 smoke demo 不小心被触发多日路径**
- 担心：orchestrator 的某些逻辑因多日改动被破坏
→ 缓解：`Orchestrator.run()` 完全保留，单日路径不改；回归测试覆盖

**[Risk 6] `MemoryEvent.day_index` 字段向后兼容**
- 已归档 memory change 的 MemoryEvent 不含该字段
→ 缓解：`day_index: int = 0`（默认 0，兼容旧调用）；新字段只在多日场景下
有语义

## Migration Plan

1. 落实现 `multi_day.py` + `carryover.py`，增量测试
2. 跑完现有 `tests/test_memory.py` + `tests/test_orchestrator.py` 确保
   单日路径零回归
3. 新增 `tests/test_multi_day.py` 覆盖 3 天 × 2 agent 的集成
4. 更新 `tools/smoke_experiment_demo.py`：保留单日入口，新增 `--multi-day`
   开关触发多日路径
5. 新建 `tools/run_multi_day_experiment.py` 作为 14 天 × N seed 的 CLI
6. 公共 API re-export 同步

**Rollback**：若本 change archive 后发现性能问题，可以 revert 仅 tools/
入口；核心库 `run_multi_day` 为 opt-in，不调就不影响。

## Open Questions

1. **Q1**：是否需要 `on_phase_start` / `on_phase_end` hook（Baseline →
   Intervention → Post 的切换）？
   倾向：不要——phase 由调用者在 `on_day_start` 内部判断 day_index 处理；
   spec 不知道 phase。
2. **Q2**：`CarryoverContext` 是否包含 per-agent 的社交邻居（拟为 social-graph
   前置）？
   倾向：**不**——那是 `social-graph` change 的事；本 change 只处理已存在的
   memory 数据。
3. **Q3**：多日 run 是否应支持 checkpointing（跑到中途保存，可续跑）？
   倾向：不——对探索性项目 overkill；14 天 ≤ 30s 不需 checkpoint。
4. **Q4**：cross-seed 聚合是否要进 `multi-day-run` spec，还是推给 `metrics`？
   倾向：**进本 spec 的最小实现**（给一个 `MultiDayResult.combine([...])`
   classmethod 即可）；丰富指标留给 `metrics`。
