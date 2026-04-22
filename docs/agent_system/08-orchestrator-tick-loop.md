# Orchestrator Tick Loop

Phase 2 中 Phase 2 的 tick 循环驱动；`synthetic_socio_wind_tunnel.orchestrator`。

## 每 tick 内部顺序

```
 ┌────────────────────────────────────────────┐
 │  1. on_tick_start(TickContext)             │  ← hook（observer_context=None）
 │                                            │
 │  2. 观察阶段（逐 agent，字典序）             │
 │     build observer_ctx:                    │
 │       - agent.build_observer_context()     │
 │       - 补 position（从 Ledger）            │
 │       - 合并为 ObserverContext              │
 │     intent = agent.step(TickContext)       │
 │                                            │
 │  3. 裁决阶段                                 │
 │     IntentResolver.resolve(intent_pool)    │
 │     ├─ 非独占 (Move/Wait/Examine) → commit  │
 │     └─ 独占 (Pickup/Door/Lock/Unlock)       │
 │         按 target_id 分组                   │
 │         字典序赢家 commit，其余 rejected    │
 │                                            │
 │  4. 提交阶段（按 agent_id 字典序）           │
 │     分派 Intent → SimulationService         │
 │     MoveIntent 展开 NavigationResult.steps  │
 │       逐 step 调 move_entity               │
 │       每成功 step → 追加 TickMovementTrace  │
 │                                            │
 │  5. 相遇扫描                                 │
 │     按 location 桶 O(trace_len)             │
 │     → EncounterCandidate[]                 │
 │                                            │
 │  6. Ledger.current_time += tick_minutes     │  ← 唯一的时间推进点
 │                                            │
 │  7. on_tick_end(TickResult)                │  ← hook
 └────────────────────────────────────────────┘
```

## Intent 分类

```
Intent
├── 非独占（直接 commit）
│   ├── MoveIntent(to_location)           → move_entity × n (逐 step)
│   ├── WaitIntent(reason)                → 不调 simulation
│   └── ExamineIntent(target)             → mark_item_examined
│
└── 独占（走 IntentResolver）
    ├── PickupIntent(item_id)             → give_item_to_entity
    ├── OpenDoorIntent(door_id)           → open_door
    ├── UnlockIntent(door_id, key_id)     → unlock_door
    └── LockIntent(door_id, key_id)       → lock_door
```

本 change 的 `AgentRuntime.step()` 只产 `MoveIntent` / `WaitIntent`；
独占类 Intent 的类型定义已存在，但要等未来 change（policy-hack /
conversation / memory）通过 PlanStep 扩展字段或外部插入机制产出。

## Hook 契约

```
on_simulation_start(SimulationContext)   ← run() 开始时一次
on_tick_start(TickContext)               ← 每 tick 开头
on_tick_end(TickResult)                  ← 每 tick 结尾
on_simulation_end(SimulationSummary)     ← run() 结束前一次
```

- 所有 hook 同步；多个 callback 按注册顺序触发。
- Callback 抛异常 → 向上传播，终止 simulation（不吞）。
- Callback MUST NOT 修改 Ledger；订阅者自己的状态由自己 service 管理。

## 约束

- `tick_minutes` 必须整除 1440（默认 5 → 288 tick/天；10 → 144；1/2/3/4/6/8/10/12/15/20/30/60 均合法）
- `num_days` 只能 = 1（多天需要 memory capability）
- Sequential 执行；Ledger 无需 thread-safe
- 确定性：同 seed + 同 atlas + 同 profile → 同 Ledger 快照

## 未来扩展点

| 未来 change | 通过什么接入 |
|---|---|
| `memory` | on_tick_end 订阅 WorldEvent 流；Replan interrupt |
| `social-graph` | on_tick_end 消费 EncounterCandidate |
| `conversation` | on_tick_end 消费 EncounterCandidate → 产对话 |
| `policy-hack` | 构造器传入或 on_simulation_start 注入 FeedItem |
| `model-budget` | agent.step() 在内部决定是否调 LLM |
| `metrics` | on_tick_end 全量订阅 TickResult，序列化到磁盘 |

---

## 附录：多日调用（multi-day-simulation change）

`Orchestrator.run()` 本身只跑 1 天；N 天由 `MultiDayRunner.run_multi_day`
分天调用 `run(day_index=i, simulated_date=...)` 实现。参数为 kwarg-only
默认 0 / None，单日调用完全不受影响。

每 tick 的 `TickContext` / `TickResult` / `CommitRecord` 现在都带
`simulated_date` + `day_index` 字段（默认 0 / 从 Ledger 派生），订阅者
按需读即可。

完整细节与 hook 时序示例见
[`14-multi-day-simulation.md`](14-multi-day-simulation.md)。
