## Context

Phase 1 + Phase 1.5 把舞台、布景、演员皮囊、数字注意力通道都建好了，
但没有"导演"告诉演员什么时候动起来。这个 change 建造 orchestrator——
Phase 2 所有能力（memory / social-graph / policy-hack / conversation /
metrics）都挂在它的 tick 循环上。

现有约束：
- `SimulationService` 是命令式 API，直接 `move_entity(...) -> Result`
- `AgentRuntime` 有 `current_step / advance_plan / next_move_location`，
  调用者负责按时序驱动
- `PerceptionPipeline.render(ctx)` 纯读，可重入
- `NavigationService.find_route(a, b)` 产出 `NavigationResult.steps: list[NavigationStep]`
- `AttentionService.mark_consumed` 已在 pipeline.render 末尾调用
- Ledger 不是 thread-safe，但 sequential 访问不出问题

三个关键决策已在 proposal 对齐：
- **Sequential** 并发模型
- **Intent** 抽象（单数，每 tick 每 agent 一个）
- **子 tick 轨迹插值** 用于相遇检测

## Goals / Non-Goals

**Goals:**
- 把 Phase 1 / 1.5 所有库函数串成一个可跑的 tick 循环
- 提供确定性（同 seed → 同 Ledger 快照）
- 为 Phase 2 后续能力提供清晰的 hook 契约
- 让 thesis 的"路上相遇"现象在 5 分钟 tick 粒度下仍可观察

**Non-Goals:**
- 多天 / 日终 reflection（memory change）
- Replan / LLM 动态决策（memory + conversation change）
- Checkpoint / resume（YAGNI）
- 并发 / 多进程（sequential 性能够，暂不优化）
- 任何 hook 订阅者的具体实现（那是 metrics / policy-hack / memory 各自的 change）

## Decisions

### D1: Intent 的层次结构与裁决范围

**决定**：5 个具体 Intent 类型，分两类：

```
Intent (base)
├── NonExclusive        # 直接按字典序提交，不进裁决器
│   ├── MoveIntent
│   ├── WaitIntent
│   └── ExamineIntent
└── Exclusive           # 走 IntentResolver 裁决
    ├── PickupIntent
    ├── OpenDoorIntent
    ├── UnlockIntent
    └── LockIntent
```

**裁决规则**：对同一 tick 内 target_id 相同的 Exclusive Intent，
按 `agent_id` 字典序挑赢家；其余 agents 收到 `SimulationResult.fail`，
`error_code=PRECONDITION_FAILED`。赢家正常执行。

**备选（不做）**：允许插件式裁决策略（优先级 / 随机）。YAGNI，需要时
单独 change 扩展。

**为什么**：thesis 实验场景下，拾取 / 开锁类冲突每天发生 0-10 次量级；
字典序足够确定性 + 可调试。Move 不冲突是 atlas 假设的推论（一个
location 可容纳多人），无需裁决器介入。

### D2: `TickContext` 的内容

`TickContext` 是 orchestrator 传给 `agent.step(ctx)` 的只读上下文。最小
必需字段：

```python
@dataclass(frozen=True)
class TickContext:
    tick_index: int            # 0-based, 当天第几个 tick
    simulated_time: datetime   # Ledger.current_time 快照
    observer_context: ObserverContext  # 当前 agent 的 observation
```

**不包含**：Ledger / Atlas 引用、其它 agent 的 intent / location——这些
让 agent 只通过 ObserverContext（即只看到它应该看到的）。Phase 2
`memory` change 会在此基础上 **扩展** `TickContext`（加 `memory_view`
字段），不修改本 change 的字段集合。

### D3: 子 tick 轨迹插值 —— Ledger 逐格写

`MoveIntent(to_location)` 在提交阶段展开：

1. orchestrator 调用 `NavigationService.find_route(from_location, to_location)`
2. 对 `NavigationResult.steps` 的每个 location id，依次调用
   `SimulationService.move_entity(agent_id, step_location)`——
   Ledger 中该 entity 的 `location_id` 依次经过所有中间位置。
3. 同步记录 `TickMovementTrace.locations`（orchestrator 内部结构），
   用于 tick 末的 O(1) 相遇扫描而不必回查 Ledger 事件流。

**每 sub-step 的 Ledger 写入语义**：

- `SimulationService.move_entity` 每次调用都会产生一组 WorldEvent：
  ENTITY_LEFT_ROOM + SOUND_FOOTSTEPS + ENTITY_ENTERED_ROOM（Phase 1 契约）。
- 对一条 n-step 的路径，总 event 数为 n × 3。
- 每次 sub-step 的 event `timestamp` SHALL 都用 tick 开始时的 Ledger
  `current_time`（同一 tick 内不推进）——所有 sub-step 在"同一 5 分钟"内
  发生；`current_time` 仅在 tick 末统一推进 `tick_minutes`。
- 若某 sub-step 返回 `SimulationResult.success=False`（例如 tick 期间
  atlas 状态变化导致中间节点不可达），orchestrator SHALL 停止剩余
  sub-step；agent 留在最后一个成功的 sub-step location，该 MoveIntent
  的整体 CommitRecord.result 取最后一个失败 SimulationResult。

**为什么 B 而不是 A（一次性跳到终点 + orchestrator 内部 trace）**：
A 更省写入（每 tick 只写 1 次），但 Ledger 看不到中间位置——以后的
`policy-hack` / `conversation` change 想要"agent 走一半时被打断"
（接到推送 → 改方向）就没有锚点，必须回头改 orchestrator 数据结构。B
先把 Ledger 模型对齐"agent 真的在路上"的语义，代价是写入量 3-10x。

**相遇检测**：tick 末：

```
for each pair (a, b) in agents where a < b:
    if trace[a].locations ∩ trace[b].locations non-empty:
        emit EncounterCandidate(
            tick=t, agent_a=a, agent_b=b,
            shared_locations=intersection,
        )
```

按 location 分桶实现：每个 location 维护"哪些 agent 在本 tick 经过过"
集合，扫 location 桶产出 pair（O(total_trace_length)，不是 O(N²)）。

### D4: 裁决与感知的先后

每 tick 内部的执行顺序：

```
1. on_tick_start(ctx)                        ← hook
2. 对每 agent (字典序):
     2a. observer_ctx = pipeline 用 Ledger 快照构造
     2b. intent = agent.step(TickContext(observer_ctx))
     2c. 收入 intent_pool[agent]
3. resolver.resolve(intent_pool) → [CommitDecision]
4. 对每个 CommitDecision (字典序):
     4a. 调 SimulationService 提交（move/open/pickup/...）
     4b. MoveIntent 成功后展开轨迹 → TickMovementTrace
5. 扫描 TickMovementTrace → encounter_candidates
6. 推进 Ledger.current_time += tick_duration
7. on_tick_end(ctx, commits, encounters)      ← hook
```

**为什么感知在决策前、裁决在提交前**：agent 看到的是"本 tick 开始时"
的世界（避免 agent 看到自己的 intent 还没提交就观察到 stale state）；
裁决是"所有 intent 都收上来"后的全局决策（避免先 commit 的 agent 比
后 commit 的占便宜——除了我们显式按字典序裁决这件事之外）。

### D5: Hook 契约

4 个 hook，签名:

```python
on_simulation_start(sim_ctx: SimulationContext) -> None
on_tick_start(tick_ctx: TickContext) -> None
on_tick_end(tick_result: TickResult) -> None
on_simulation_end(final_summary: SimulationSummary) -> None
```

- Hook 是**同步**的——这个版本不考虑异步。hook 内部抛异常会 abort 整个
  simulation（不容错）。
- 注册方式：`orchestrator.register_hook(hook_name, callback)`——可叠多个
  callback，按注册顺序触发。
- hook callback MUST NOT 修改 Ledger 直接（保持 CQRS）——如果需要写入
  （如 metrics 记录），由 callback 自己的 service 管理它自己的状态。

**备选（不做）**：基于 WorldEvent 的 pub/sub 总线。更通用但对本 change
过度设计——现在只有 tick 边界这一种事件要订阅，简单回调已够。

### D6: 单天循环的边界

Orchestrator 构造器接 `num_days: int = 1`；如果 >1 立即 raise
`NotImplementedError`：

```python
if num_days > 1:
    raise NotImplementedError(
        "Multi-day simulation requires `memory` capability for daily "
        "reflection + next-day plan generation. See phase-2-roadmap."
    )
```

这是主动占位——多天是未来 change 的入口，现在挖坑但不填。

### D7: 与 AttentionService / PerceptionPipeline 的集成

Orchestrator 构造器接受：

```python
Orchestrator(
    atlas: Atlas,
    ledger: Ledger,
    agents: list[AgentRuntime],
    *,
    simulation: SimulationService | None = None,
    pipeline: PerceptionPipeline | None = None,
    navigation: NavigationService | None = None,
    attention_service: AttentionService | None = None,
    tick_minutes: int = 5,
    seed: int = 0,
    num_days: int = 1,
)
```

- 若 `pipeline` 未传，orchestrator 构造一个 sensible default
  （`PerceptionPipeline(atlas, ledger, include_digital_filter=bool(attention_service), attention_service=attention_service)`）
- `AgentRuntime.attention_service` 已由 realign-to-social-thesis 加入；
  orchestrator 不再重复注入。

### D8: 确定性与 seed

`seed: int` 参数给到两处：
- `IntentResolver(seed=seed)`：决定"多 agent 字典序相同"时的 tie-break（理论
  上不会发生，但字典序稳定 + 固定 seed 双保险）
- 任何 orchestrator 内部的随机选择（例如"agent 在 dead-end 原地等" 的
  behavior 切换）—— 目前不存在但保留接口

不传 `seed` 到 AttentionService / Planner：那些各自有自己的 seed。

`EncounterCandidate.shared_locations` SHALL 为 `tuple(sorted(intersection))`
保证不同运行间 tuple 内顺序一致（否则 Ledger 快照虽然一致，但 TickResult
序列化不一致）。

### D9: Intent → SimulationService 方法映射

Orchestrator commit 阶段按 Intent 类型分派到 SimulationService 的现有方法：

| Intent           | SimulationService 方法                             | 备注               |
|------------------|----------------------------------------------------|--------------------|
| `MoveIntent`     | `move_entity(agent_id, step_location)` × n        | 逐 step 调用（D3） |
| `WaitIntent`     | 不调 simulation，直接产出 `SimulationResult.ok()` | 无事件             |
| `ExamineIntent`  | `mark_item_examined(target_id, agent_id)`         | 返回 ok/fail       |
| `PickupIntent`   | `give_item_to_entity(item_id, agent_id)`          | 返回 ok/fail       |
| `OpenDoorIntent` | `open_door(door_id, agent_id)`                    | 返回 ok/fail       |
| `UnlockIntent`   | `unlock_door(door_id, agent_id, key_id)`          | 返回 ok/fail       |
| `LockIntent`     | `lock_door(door_id, agent_id, key_id)`            | 返回 ok/fail       |

- 所有 `SimulationResult` 原样填入 `CommitRecord.result`。
- WaitIntent 刻意不产生 WorldEvent（"等待"在 thesis 语境下不是可感知事件）。
- `tick_minutes` SHALL 整除 1440（24*60）；否则构造时 raise `ValueError`。
  `num_ticks_per_day = 1440 // tick_minutes`。

### D10: plan advance 与 at_destination 语义

`AgentRuntime.step(tick_ctx)` 在内部自管 plan 状态机——orchestrator 不读
plan 细节（保持封装）：

```python
def step(self, tick_ctx: TickContext) -> Intent:
    if self.plan is None:
        return WaitIntent(reason="no_plan")

    # 1. 自动 advance：如果当前 step 的时间窗已过
    while self._current_step_expired(tick_ctx.simulated_time):
        advanced = self.plan.advance()
        if advanced is None:
            return WaitIntent(reason="plan_exhausted")

    current = self.plan.current()
    if current is None:
        return WaitIntent(reason="plan_exhausted")

    # 2. 到达 destination 但 step 时间窗未过 → WaitIntent
    if (current.action == "move" and
        self.current_location == current.destination):
        return WaitIntent(reason="at_destination")

    # 3. 按 action 映射到 Intent
    match current.action:
        case "move":
            return MoveIntent(to_location=current.destination)
        case _:
            return WaitIntent(reason=current.activity or "unspecified")
```

**关键约束**：
- advance 仅发生在 step() 内部；orchestrator **绝不**直接调 `plan.advance()`。
- 本 change 的 `step()` 只产 `MoveIntent` 或 `WaitIntent`——其它 Intent
  类型（Examine/Pickup/OpenDoor/Unlock/Lock）**类型存在但不由 step() 产出**，
  留给未来 change（policy-hack / conversation / memory）通过 plan step
  扩展 or 外部插入。这避免了在 PlanStep 现有字段（无 target_id）上强行
  硬编码 Examine/Pickup 生成规则。

**备选（不做）**：让 `step()` 为 `stay/interact` 类 plan step 也产出 Examine/Pickup。
PlanStep 字段不够用，会逼 Planner 吐出 orchestrator 要的字段 → 跨模块耦合
升高。YAGNI，后续 change 补。

### D11: ObserverContext 的 position 字段

`ObserverContext(entity_id, position, location_id, ...)` 必需 `position: Coord`。
Phase 1 的 `AgentRuntime.build_observer_context()` 返回 dict 且不含 position。
Orchestrator 在构造 ObserverContext 时 SHALL 从 `Ledger.get_entity(agent_id).position`
直接读，合并到 dict：

```python
ctx_dict = agent.build_observer_context()
entity = ledger.get_entity(agent.profile.agent_id)
ctx_dict["position"] = entity.position if entity else Coord(0, 0)
observer_ctx = ObserverContext(**ctx_dict)
```

AgentRuntime 接口不变（避免破坏 Phase 1 tests）；position 的"桥接"由
orchestrator 负责。未来若 AgentRuntime 改为直接返回 ObserverContext 实例，
可再调整，独立 change。

## Risks / Trade-offs

**[R1] Intent 抽象改了 agent 层的表面积**
→ Mitigation：原有 `current_step / advance_plan / next_move_location`
  全部保留，`step()` 作为新的"高层入口"。现有 tests 不 touch。

**[R2] 子 tick 轨迹插值与 NavigationService 的接口耦合**
→ `NavigationResult.steps` 是 Phase 1 的稳定契约；orchestrator 只读不改。
  如果以后 Navigation 改 step 结构（例如引入立体路径），此处需跟进。

**[R3] Sequential + 逐 step Ledger 写在 1000 agent 下可能慢**
→ 估计：Phase 1.5 quick-scale 15s（100×72，每 tick 1 次 move）；逐 step
  写放大 3–10x，quick-scale 可能 45–150s。接近 120s 的 scale-audit 阈值。
  如果 quick-scale FAIL，先考虑优化 SimulationService.move_entity 的事件
  生成（batch mode），再考虑并发。`fitness-audit` 会自动捕捉 regression。

**[R4] Hook 抛异常导致 simulation 崩溃**
→ 接受。hook 订阅者应该保证不抛；否则简化为"失败即终止"比"吞异常
  假装成功"更好（后者难调试）。

**[R5] 冲突裁决只按字典序，agent 可能因此被系统性"歧视"**
→ 接受。现在场景下字典序稳定 + 可复现就够；后续若发现某 agent 被永远
  淘汰，单独开 change 支持随机化 / 公平性策略。

**[R6] `MoveIntent` 展开为 NavigationResult 可能走不通（目标不可达）**
→ Fallback：`SimulationService.move_entity` 返回 fail，agent 留在原地，
  orchestrator 记录 `TickMovementTrace` 为空（没走路），encounter 不产出。

## Migration Plan

1. 创建 `synthetic_socio_wind_tunnel/orchestrator/` + `synthetic_socio_wind_tunnel/agent/intent.py`
2. `AgentRuntime.step(ctx)` 内部复用现有 `current_step` / `next_move_location`
3. `tests/test_agent_intent.py` 覆盖 Intent 数据模型 + `step()` 的各类 plan
4. `tests/test_orchestrator.py` 覆盖 tick 循环 / 冲突裁决 / 相遇检测 / hook
5. `__init__.py` re-export
6. 跑 `make fitness-audit`：验证 `phase2-gaps.orchestrator` 由 FAIL → PASS
7. 跑 `make fitness-audit-full`（可选）：验证 1000×288 单天能跑完

### 回滚
- 删除 `orchestrator/` 与 `agent/intent.py` + 撤回 `__init__.py` 的 re-export
  即可。Phase 1 / 1.5 行为不受影响。

## Open Questions

- ~~**Q1**：MoveIntent 展开是逐 step 写 Ledger 还是一次性跳？~~
  **已决策（2026-04-20）**：逐 step 写 Ledger（选项 B）。
  - Ledger 逐次经过中间位置，为未来 mid-tick interrupt 打基础。
  - 代价：每 MoveIntent 触发 n_substeps × 3 条 WorldEvent，Ledger 写入放大。
  - 后续开 `orchestrator` archive 后跑 `make fitness-audit-full`，scale-baseline
    数字 SHALL 相对 Phase 1.5 基线上升 3–10x（仍在同一量级）。

- **Q2**：如果 `agent.step` 返回 `Intent` 但 `current_step` 已完成整天计划，
  step 应该一直返回 `WaitIntent` 还是抛异常？
  → 建议：返回 `WaitIntent("plan_exhausted")`；orchestrator 不因"某 agent
  计划跑完"中止整个 simulation。

- **Q3**：`EncounterCandidate` 要不要写 Ledger？
  → 建议：**不写**。候选对只是临时结构，由 `conversation` change 消费。
  orchestrator 通过 `on_tick_end(tick_result)` 传给 hook 订阅者。
  若订阅者想持久化，自己写。
