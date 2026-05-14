## Why

跑 14 天 viz_demo 后看 position trace 分布：

```
changes/tick 分布 (修前):
  22 段/tick: 88 occurrences
  23 段/tick: 91 occurrences
  24 段/tick: 57 occurrences
```

含义：agent 一个 tick (5 min) 走 22+ street segments ≈ **1.5km / 5min ≈ 24 km/h 慢跑速度**。orchestrator 的 `_dispatch_move` 一次性走完 NavigationService 的全段路径——agent 等于 teleport。

后果：
1. 视觉上 14 天 replay 看到 agent 在家死蹲然后突然瞬移 1.5km 到 cafe
2. encounter 检测虚高——同 tick 多 agent 集中在 cowper_street，"擦肩而过"算 encounter
3. mid-route replan 几乎不可能触发——push 到达时 agent 早走完了
4. thesis 因果链"push → 改变路径 → 改变 encounter"被人为加速无法测

进一步思考：thesis 的 ABS 数据已经采样了 `vehicles_at_dwelling` (0/1/2/3+ 比例 9/50/32/9%)。如果把"有车"映射到更高 per-tick 速度，就能 **mock 出 walker vs driver 的 thesis 差异**——hp 推 nearby cafe 对走路的人有效（容易停），对开车经过的人无效（速度太快过站）。

## What Changes

### Atlas 层

- **`OutdoorArea.access_mode: str ∈ {pedestrian, motor, mixed}`** 新字段
  - `pedestrian`: OSM `footway` / `path` / `steps` / `cycleway` / `pedestrian` / `corridor`
  - `motor`: OSM `motorway` / `motorway_link` / `trunk` / `trunk_link`
  - `mixed`: 其它 (`residential` / `primary` / `secondary` / `service` / ...)
- `cartography/importer.py` `_highway_to_access_mode()` helper 从 OSM tag 映射
- Lane Cove atlas 重建后：2124 pedestrian / 1757 mixed / 164 motor

### Agent 层

- **`AgentProfile.walking_speed_m_per_min: float = 80.0`** 默认步行 5 km/h
- **`AgentProfile.prefer_driving: bool = False`** 是否倾向开车 (有车户)
- `sample_population` 按 `vehicles_at_dwelling` 推导 (基于 ABS 2021 SAL12275 实测):
  - `"0"`: 80 m/min / `prefer_driving=False`  (纯步行，9%)
  - `"1"`: 150 m/min / `prefer_driving=True`  (1 车混合，50%)
  - `"2"`: 250 m/min / `prefer_driving=True`  (2 车主开，32%)
  - `"3plus"`: 280 m/min / `prefer_driving=True` (重度，9%)

### NavigationService 层

- `find_route(...)` 新参数 `mode: str = "any"`，取值 `walking` / `driving` / `any`
- **walking**: 过滤掉 access_mode == "motor" 的 edge，无车 agent 不会走高速
- **driving**: 不过滤 (drivers 可以停车走最后一段 pedestrian 路)
- **any**: 默认，完全不过滤 (向后兼容)

### Orchestrator 层

- `Orchestrator.__init__` 加 `walking_speed_m_per_min: float = 80.0` 全局默认
- `_dispatch_move(...)` 重写：
  - 按 `agent.profile.walking_speed_m_per_min × tick_minutes` 计算 per-tick 距离 budget
  - 长 route 不再一次走完——按 NavigationStep 累计距离，达到 budget 即停
  - 剩余 steps 保存到 `agent._in_flight_route_remaining`
  - 下一 tick 自动 resume；agent 在 plan_step 时间窗内多 tick 走完
  - `agent._in_flight_target` 与 plan 的新 destination 不一致时重新规划
- 调 `nav.find_route(mode=...)` 按 `agent.prefer_driving` 选 mode
- mode-filter route 找不到时 fallback `mode="any"` (避免 over-filter 卡死)

### AgentRuntime 层

- `AgentRuntime._in_flight_route_remaining: list = field(default_factory=list)` 新字段
- `AgentRuntime._in_flight_target: str | None = None` 新字段
- 跨 tick 持久化未走完的 route segments

### Non-goals

- **不真模拟车辆 entity** —— driver 仍然是单个 dot，只是速度快
- **不实现停车/上下车状态机** —— driving agent 通过 pedestrian 段 fallback 当作"末端步行"
- **不区分早晚高峰** —— 速度是 per-agent 常量
- **不引入红绿灯/拥堵** —— 仿真粒度不到
- **不改 D2 publishable 协议** —— 但 D1' 重跑必须用新逻辑

## Capabilities

### Modified Capabilities

- `cartography`: OutdoorArea 加 `access_mode` 字段；importer 从 OSM tag 映射
- `agent`: AgentProfile 加 `walking_speed_m_per_min` + `prefer_driving`；sample_population 从 `vehicles_at_dwelling` 推导
- `navigation`: `find_route` 加 `mode` 参数过滤 edge
- `orchestrator`: `_dispatch_move` 改为 budget-aware 多 tick；TickResult.movement_traces 仍单 tick 内全部 capture

## Impact

- **代码**:
  - `synthetic_socio_wind_tunnel/atlas/models.py` (OutdoorArea.access_mode)
  - `synthetic_socio_wind_tunnel/cartography/importer.py` (helper + 注入字段)
  - `synthetic_socio_wind_tunnel/agent/profile.py` (新字段)
  - `synthetic_socio_wind_tunnel/agent/population.py` (sample 时映射)
  - `synthetic_socio_wind_tunnel/engine/navigation.py` (find_route mode)
  - `synthetic_socio_wind_tunnel/orchestrator/service.py` (_dispatch_move budget)
  - `synthetic_socio_wind_tunnel/agent/runtime.py` (in-flight state)
- **数据**:
  - `data/lanecove_atlas.json` 重建 (access_mode 字段持久化)
  - 旧 archive 实验数据 deprecated (无 access_mode；旧 trace 无 budget)
- **测试**: 250 个相关 test 通过 (regression)
- **预期效果**:
  - Per-tick changes 分布: walker median 5 / driver median 15
  - encounter 数下降 (少了 drive-by inflation 部分)
  - thesis 信号方向应保持 (pf > baseline > gd)
