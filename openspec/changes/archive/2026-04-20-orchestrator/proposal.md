## Why

Phase 1 给每个 agent 准备了身份 + 日计划 + 感知能力；Phase 1.5 的
`realign-to-social-thesis` 又补了数字注意力通道。但到现在为止，整个系统
**没有驱动者**——`AgentRuntime`、`SimulationService`、`PerceptionPipeline`
都是库函数，需要外部调用方串起来才能"跑"。

`data/fitness-report.json`（由 `make fitness-audit` 生成）把这个缺口明说了：

- `phase2-gaps.orchestrator`（FAIL，mitigation=orchestrator）：
  `synthetic_socio_wind_tunnel.orchestrator` 模块不存在。
- `e2.*`（三条 SKIP，mitigation=cartography）：没法跑"运行期 unlock door →
  路径变化"这类实验——因为没有 tick 循环来运行期。
- `scale.wall-time`（PASS 但弱）：只测了 render，没测 "1000 agent 每 tick
  真实移动 + 相遇检测" 的负载；那个负载要 orchestrator 才能定义。

此外，thesis 的**核心现象**是"路上相遇"——两个 agent 在 5 分钟 tick 内经过
同一街道但终点已分开。如果 orchestrator 只扫 tick 末的 location，这类相遇
全被漏掉，spatial-unlock / digital-lure 实验的核心机制就测不出来。

这些缺口共同说明：orchestrator 是 Phase 2 的**前置 change**，没有它，
memory / social-graph / policy-hack / conversation / metrics 都没地方挂。

## What Changes

### 1. 新增 `orchestrator` capability（NEW）

提供 `synthetic_socio_wind_tunnel.orchestrator` 模块，承担三件事：

1. **Tick 驱动**：按固定步长（默认 5 分钟）推进 Ledger 时钟；每 tick 为每个
   agent 走一遍"意图 → 裁决 → 提交 → 感知"流程。
2. **Intent 抽象**：新增 `agent.step(tick_ctx) -> Intent` 接口（单数，
   每 tick 每 agent 一个意图，与现有 DailyPlan 一步一动作对齐）。
   Intent 是"想做什么"的声明（`MoveIntent` / `OpenDoorIntent` /
   `PickupIntent` / `WaitIntent` / `ExamineIntent`）；orchestrator **仅对
   明显互斥类型**（`OpenDoorIntent` / `PickupIntent` / `LockIntent` /
   `UnlockIntent`）走冲突裁决器；`MoveIntent` / `WaitIntent` /
   `ExamineIntent` 直接按字典序提交，不裁决。
3. **路径相遇检测（子 tick 轨迹插值 + Ledger 逐格写）**：
   `MoveIntent` 在 commit 时展开为 `NavigationResult.steps` 序列；
   每个 sub-step SHALL 调一次 `SimulationService.move_entity`，
   使 Ledger 中 entity 的 location_id 依次经过所有中间位置
   （而非一次性跳到终点）。这让 "agent 走一半时 location 变化"对后续的
   `conversation` / `policy-hack` 可见，为未来的 mid-tick interrupt 打地基。
   Orchestrator 额外维护 tick 内 `TickMovementTrace`，tick 末扫描 agent
   对的 trace 位置交集，产出 "encounter 候选对"。
   **代价**：每 MoveIntent 触发 n_substeps × 3 条 WorldEvent（Phase 1
   `move_entity` 本来就产生 ENTITY_LEFT_ROOM / SOUND_FOOTSTEPS /
   ENTITY_ENTERED_ROOM 三条），Ledger 写入量较 Phase 1.5 scale baseline
   放大 3–10 倍；本 change 完成后 `scale-baseline` 的数值 SHALL 刷新。

配套约束：

- Sequential 并发（按 `agent_id` 字典序）；Ledger 无需 thread-safe。
- 确定性：同一 seed + 同一 atlas + 同一 profile seed SHALL 逐 tick 产出
  一致 Ledger 快照。
- 暴露 hook：`on_tick_start` / `on_tick_end` / `on_simulation_start` /
  `on_simulation_end` 回调——metrics / policy-hack / memory 等后续 change
  通过这些接入，不需要改 orchestrator 本身。

### 2. 修订 `agent` capability（MODIFIED）

新增 `agent.intent` 模块（Intent 类型层次）+ `AgentRuntime.step(tick_ctx)`
方法。原有 `current_step / advance_plan / next_move_location` 保留，内部
由 `step(...)` 调用：

- `Intent` 基类 + 具体子类（7 个）：`MoveIntent(to_location)` /
  `OpenDoorIntent(door_id)` / `PickupIntent(item_id)` /
  `UnlockIntent(door_id, key_id)` / `LockIntent(door_id, key_id)` /
  `WaitIntent(reason)` / `ExamineIntent(target_id)`。
- 所有 Intent frozen / 可哈希，与 `attention-channel` 的数据模型风格一致。
- `AgentRuntime.step(tick_ctx: TickContext) -> Intent`（单数）是纯函数：
  读 ObserverContext + 当前 plan step，输出恰好一个 Intent，不写 Ledger。
  若当前 plan 已走完或无动作，返回 `WaitIntent`。
- 原 `AgentRuntime.next_move_location()` / `advance_plan()` / `current_step()`
  保留；`step()` 是更高层的包装，内部复用它们。不做 deprecated 标记
  （下层接口仍然有调试价值）。

### 3. Non-goals

- **不**做多天循环。`Orchestrator(num_days=1)` 是本 change 唯一合法取值；
  `num_days>1` SHALL raise `NotImplementedError`，占位给未来 `memory` change
  接入日终 reflection。
- **不**做 replan / interrupt。orchestrator 只按已有的 DailyPlan 执行；
  policy-hack 推送、对话打断 → 都暂时不触发重规划（`insert_interrupt` 仍
  可手动用于测试）。真正的 replan 由 `memory` + `conversation` 联合能力
  决定，独立 change。
- **不**做 checkpoint / resume。1000×288 一天 45–60 分钟跑完可重来；短期
  不值得做中断恢复。
- **不**引入并发 / 多进程。Sequential 跑到撑不住前不做优化。
- **不**实现任何 hook 的订阅者（metrics / policy-hack / memory 的具体逻辑
  都在各自的 change 里）；本 change 只暴露接口并验证 hook 会被正确触发。
- **不**修改 `atlas` / `ledger` / `simulation` / `navigation` / `collapse` /
  `perception` / `attention-channel` / `cartography` / `map-service` /
  `fitness-audit` 的已冻结 Requirement。

## Capabilities

### New Capabilities
- `orchestrator`: tick 循环驱动；Intent 收集 + 裁决 + 批量提交；子 tick 轨迹
  插值 + 路径相遇候选对产出；生命周期 hook

### Modified Capabilities
- `agent`: 新增 `Intent` 层次 + `AgentRuntime.step(tick_ctx)`；原有 Phase 1
  公共 API 保留、行为兼容

## Impact

### 受影响代码
- `synthetic_socio_wind_tunnel/orchestrator/`（新）—
  `models.py`（TickContext, EncounterCandidate, HookRegistry）、
  `intent_resolver.py`（冲突裁决）、
  `service.py`（Orchestrator + tick 主循环）
- `synthetic_socio_wind_tunnel/agent/intent.py`（新）— Intent 类型层次
- `synthetic_socio_wind_tunnel/agent/runtime.py` — 加 `step(tick_ctx)` 方法；
  老方法保留但逐步迁移到 Intent 内部
- `synthetic_socio_wind_tunnel/fitness/audits/phase2_gaps.py` — `orchestrator`
  probe 由 FAIL 自动转 PASS（依靠 `_module_exists("...orchestrator")` 自动生效）
- `synthetic_socio_wind_tunnel/__init__.py` — re-export `Orchestrator` / 关键 Intent 类
- `tests/test_orchestrator.py`（新）— tick 循环 / 冲突裁决 / 路径相遇 / hook 触发
- `tests/test_agent_intent.py`（新）— Intent 数据模型 + `AgentRuntime.step`

### 不受影响（保持兼容）
- Atlas / Ledger / Simulation / Navigation / Collapse / Perception /
  Cartography / MapService / AttentionChannel / FitnessAudit 的 Requirement
- 已归档 change；Phase 1 所有测试
- Lane Cove atlas 数据；enrich-map 流水线

### 依赖变化
- 无新增第三方依赖。

### 预期成果
- 完成后 `phase2-gaps.orchestrator` 在 fitness report 中自动由 FAIL → PASS。
- 审计报告的 `scale-baseline` 条目 SHALL 转为跑"真实 orchestrator 单天",
  1000×288 应在 60 分钟内单机完成。
- 为 `memory` / `policy-hack` / `conversation` / `metrics` 四个 Phase 2
  change 提供确定的 hook 契约。
