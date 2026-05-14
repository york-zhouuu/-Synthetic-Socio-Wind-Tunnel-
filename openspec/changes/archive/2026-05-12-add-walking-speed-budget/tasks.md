## 1. Atlas / Cartography

- [x] 1.1 `atlas/models.py::OutdoorArea` 加 `access_mode: str = "mixed"` 字段
- [x] 1.2 `cartography/importer.py` 加 `_PEDESTRIAN_HIGHWAYS` / `_MOTOR_ONLY_HIGHWAYS` frozenset + `_highway_to_access_mode(highway_type)` helper
- [x] 1.3 importer `_extract_street_segments` (~line 745) 调 helper 注入 `access_mode` 字段
- [x] 1.4 重建 Lane Cove atlas → 2124 pedestrian / 1757 mixed / 164 motor segments

## 2. Agent population

- [x] 2.1 `agent/profile.py::AgentProfile` 加 `walking_speed_m_per_min: float = 80.0` + `prefer_driving: bool = False` 字段
- [x] 2.2 `agent/population.py::sample_population` 按 `vehicles_at_dwelling` 推 speed/driving (映射 0/1/2/3+ → 80/150/250/280)
- [x] 2.3 现有 `tests/test_agent_population.py` 不 regress；Pre-flight audit 验证 100 agent 分布对齐 ABS

## 3. NavigationService

- [x] 3.1 `engine/navigation.py::find_route` 加 `mode: str = "any"` 参数
- [x] 3.2 A* 循环 inner loop 加 mode filter：walking → 跳 motor edges；driving + any → 不过滤
- [x] 3.3 Pre-flight audit 验证：walker 0/6 经过 motorway；driver 0/50 route 失败

## 4. Orchestrator budget

- [x] 4.1 `orchestrator/service.py::Orchestrator.__init__` 加 `walking_speed_m_per_min: float = 80.0` 参数 + `__slots__`
- [x] 4.2 `_dispatch_move` 改造：算 `tick_budget_m = tick_minutes × agent_speed`；segment 循环累计距离，达 budget 停
- [x] 4.3 in-flight state：剩余 steps 存 `agent._in_flight_route_remaining` + target；下 tick resume
- [x] 4.4 target change 时丢弃旧 in-flight 重新规划
- [x] 4.5 mode-filter route 失败时 fallback `mode="any"`

## 5. AgentRuntime state

- [x] 5.1 `agent/runtime.py::AgentRuntime` 加 `_in_flight_route_remaining: list` + `_in_flight_target: str | None` 字段
- [x] 5.2 跨 tick 持久化未走完的 route

## 6. Pre-flight audit

- [x] 6.1 Audit B: route reachability per agent mode → walker 0/6 fail / driver 0/50 fail
- [x] 6.2 Audit C: walker 0% routes touch motorway
- [x] 6.3 Audit per-tick changes 分布 by speed bucket: 80=5/11, 150=10/18, 250=15/26, 280=17/25 (median/max)
- [x] 6.4 Audit in-flight state 切换无泄漏 → 0/9748 non-adjacent
- [x] 6.5 pf intervention 不破坏 walking_speed (model_copy 只改 digital)

## 7. 验证

- [x] 7.1 全套 250+ test PASS (orchestrator / agent / navigation / variant smoke)
- [x] 7.2 max changes/tick 24+ → 13 (修前/修后 同 protocol)
- [x] 7.3 median changes/tick 11-12 → 5-6
- [ ] 7.4 14-day × 4 variant viz_demo 重跑验证 thesis direction 保持 (defer 到 archive 后)

## 8. 文档 + archive

- [ ] 8.1 更新 `docs/limitations-ethics.md`：加段 "drive-by encounter inflation ~4-10%" + "speed 数值未实证 calibration"
- [ ] 8.2 更新 `CLAUDE.md` 关键不变量段：walking_speed_m_per_min 字段；access_mode 字段；ABS 速度映射
- [ ] 8.3 archive 该 change (`openspec archive add-walking-speed-budget`)
