## Context

`add-per-tick-position-logging` 暴露 per-tick agent 位置变化分布——发现单 tick
最多走 24 个 street segment ≈ 1.5km/5min。orchestrator 现在的 `_dispatch_move`
一次循环走完 NavigationService.find_route 的全段路径，agent 等于 teleport。
本 change 加 walking speed budget，把"长路径"分散到多 tick，同时利用已有的
ABS `vehicles_at_dwelling` 数据 mock 出 walker vs driver。

## Goals / Non-Goals

**Goals:**

1. Per-tick 最大移动距离严格受限于 `agent.walking_speed × tick_minutes`
2. 长 route 跨多 tick 走完 (resume 状态在 AgentRuntime)
3. agent speed 由 ABS `vehicles_at_dwelling` 推导 (deterministic)
4. NavigationService 按 mode 过滤 edge，walker 不走高速
5. 现有 250+ test 全过 regression

**Non-Goals:**

- 不引入 Vehicle entity / 停车 / 加油等状态
- 不改 publishable D2 协议参数
- 不区分早晚高峰
- 不实现智能体可选 mode (per trip)——always uses profile.prefer_driving

## Decisions

### D1 · 速度映射来源——ABS vs simulated

**选 ABS 实测**：用 `vehicles_at_dwelling` (已在 LANE_COVE_PROFILE 里) 直接映射。
不需要 demographic 二次假设。Lane Cove 2021 census SAL12275 实测：

| vehicles | % | speed (m/min) | 5min budget |
|---|---|---|---|
| 0 | 9.2% | 80 | 400m |
| 1 | 50.5% | 150 | 750m |
| 2 | 31.7% | 250 | 1.25km |
| 3+ | 8.6% | 280 | 1.4km |

**为什么 1 车 = 150 not 250**: 城市平均出行含停车+末端步行+短程纯步，1-车户大量
短途仍步行；250 m/min 是 "纯开车含停车" 的均速。3+ 给 280 反映 (a) 重度依赖车
(b) 也兼少量短途步行的现实。这些数字是 first-order 估计，**不基于实证**校准，
publishable 报告需 disclose。

### D2 · NavigationService mode 滤的不对称性

**选 walker 严格 / driver 宽松**：

- `mode="walking"`: 跳过 `access_mode=="motor"` 的 edge——无车者不走高速
- `mode="driving"`: **不过滤**——因为 destination 通常是 building，建筑入口
  通过 pedestrian footway 连接，过滤会让 86% driver 找不到路 (实测)

哲学含义：driver 不是"永远开车"，是"愿意开车但能也走"。最后一段 pedestrian
路被当作"停车后步行"。这个 asymmetry 让 driver 几乎不丢路径，walker 严格避免
motorway——和现实贴合。

### D3 · TickResult.entity_locations + movement_traces 不变

per-tick 位置日志机制 (`add-per-tick-position-logging`) 不变。budget 实施在
orchestrator 一层，对下游 (PositionTraceRecorder / encounter detection) 透明：
更多 tick 中、每 tick 更少 segments。

### D4 · in-flight 状态保存位置

**选 AgentRuntime**：runtime 已经是 mutable，加 2 个字段:
- `_in_flight_route_remaining: list[NavigationStep]`
- `_in_flight_target: str | None`

`_dispatch_move`:
1. 若 `_in_flight_target == intent.to_location`: 续走 `_in_flight_route_remaining`
2. 否则: 调 `nav.find_route` 重算 + 设 `_in_flight_target = intent.to_location`
3. 累计走 segments 直到 `cumulative_distance >= budget` 或 route 走完
4. 若 route 走完: 清 `_in_flight_*`；若 budget 用完: 保存剩余

`AgentRuntime.decide_action_for_tick` 不动——agent 只要 plan 没变 destination 就
还是发同样 MoveIntent。

### D5 · 速度 always 单步突破——保最小进度

边界 case：单个 street segment > budget (例：长高速段)。如不处理 agent 会卡。
**总走至少 1 step / tick**，然后立即 break——even if budget exceeded:

```python
for nav_step in steps_to_walk:
    result = move_entity(...)
    consumed_distance += step.distance
    idx += 1
    if consumed_distance >= tick_budget_m:
        break
```

实测 max changes/tick = 26 (driver) → 1.3km / 5min = 15.6 km/h——合理城市开车速。

### D6 · 不同速度下 encounter 检测策略

仍按现行：tick 末 entity_locations 取 + intra-tick traces 一起喂 encounter
detector。已知问题：driver 高速通过 26 segments 会算 ~10 drive-by encounters
("擦肩而过")。占总 encounter ~4-10%，**先 disclose 为 limitation，不在本
change 修**。后续 change 可在 noticing_prob 加 transit discount。

## Risks / Trade-offs

- **[encounter inflation]** drive-by 占 4-10%；thesis direction 应不变但效应
  size 可能高估。Mitigation: 在 `docs/limitations-ethics.md` 加段说明
- **[walking mode over-filter]** 0.5% walker route 可能在边缘情况无解；用
  fallback to `mode="any"` 保底
- **[determinism 与 RNG 序列]** vehicles_at_dwelling 已经在 RNG 序列里采，
  speed 是 deterministic 函数。**byte-equal 保证不破**
- **[atlas cache 兼容]** 旧 atlas 没 access_mode 字段 → 加载时 Pydantic
  默认 `"mixed"`，nav 全无过滤——退化为旧行为。重建一次后即一致
- **[14d 跑时间增加]** budget cap 让长 commute 分多 tick，total ticks 不变
  (288/day)，但 movement_traces 更多——位置 trace 文件可能从 25MB 增到
  35MB。可接受

## Migration Plan

1. atlas/models.py 加字段 (默认 "mixed" 保兼容)
2. cartography/importer.py 加 helper + 注入字段
3. agent/profile.py 加 2 字段 (默认 80.0 / False)
4. agent/population.py sample 时映射
5. engine/navigation.py find_route 加 mode 参数 (默认 "any")
6. orchestrator/service.py _dispatch_move 重写
7. agent/runtime.py 加 2 个 in-flight 字段
8. 重建 atlas 一次
9. pytest 全套 (250+)
10. Pre-flight audit (本 change 的 §pre-flight 已跑)

## Open Questions

- 速度数值 calibration：80/150/250/280 是直觉，应在 publishable §limitations
  披露为 "first-order estimate, not empirically tuned"
- 是否对 protag 特殊处理 (LLM 决策时机选 mode)：本 change 不做
- 是否引入夜间车少 / 早晨堵车？speed 时间相关性：未来 change
