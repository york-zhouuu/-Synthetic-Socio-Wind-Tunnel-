## Why

D1' DeepSeek smoke 跑完后审计 `space_activation` 发现：

```
dwell by category (baseline, 14 day × 100 agent):
  street       375,855 ticks  (93%)
  playground    27,345 ticks   (7%)
  residential        0          (0%)
  cafe / shop / office / restaurant / school   0   (0%)
```

100/100 agent 14 天每晚都在街段过夜，没有任何 agent 进过任何建筑——这是
thesis 因果链的塌方。Thesis 假设是"反向超在地推送把人从屏幕拉回**附近**"，
但若 agent 根本没有"家""办公室""咖啡馆"这些**附近的容器**，所谓"附近性"就
不存在；所有 variant 之间的差异都是发生在 outdoor 街段之间的差异，与 thesis
要测的"打破附近性盲区"无关。

根因（一句话）：`tools/smoke_experiment_demo.py::_pick_connected_destinations`
只从 `atlas.region.outdoor_areas` 选点。该返回的 `destinations` 同时被用作
agent 的 `home_locations` 和 scripted_plan 的所有目的地。结果：

- `home_location` 强制是街段（5480 residential building 全被跳过）
- scripted_plan 整天在街段之间打转（5722 building 全被跳过）

5700 个建筑↔街道 connection 在 atlas 里**已存在且可用**，
`atlas.list_residential_buildings()`、`atlas.list_buildings_by_type()`
等 typed accessor 在 `cartography` spec 早已契约化并实现——纯粹是 wiring 没接通。

这是必须修的——所有已 archive 的实验数据（D1' / D2 in-flight / Phase 2 各 change
的 verification run）对 thesis 的支撑力都被这个 bug 削弱；修完后从 1-seed smoke
开始重跑 D1' 验拟真度，再决定 D2 是否值得重启。

## What Changes

- **新增 typed destinations 采样**：`suite-wiring` 层 SHALL 改用三个分类池构造
  agent 的位置生态：
  - `home_pool`：residential building，按容量约束分配，每户最多 N 人（默认 4，沿用
    cartography spec 的 `capacity = min(12, floors * 4)`）
  - `work_pool`：office / school / commercial / community / hospital building，按
    profile.work_mode（full-time/part-time/retired/student/...）决定是否分配
  - `poi_pool`：cafe / restaurant / shop / park / playground / garden / community
    building——scripted_plan 的"errand / leisure / outing" step 从此池抽
- **BREAKING：`AgentProfile.home_location` 语义**：仍为 location_id，但**SHALL** 是
  `building_type == "residential"` 的 building（不再允许 outdoor_area 作为 home）
- **BREAKING：`_pick_connected_destinations` API**：拆为
  `_pick_home_pool(atlas, count, rng)`、`_pick_work_pool(atlas, count, rng)`、
  `_pick_poi_pool(atlas, count, rng)`；旧函数保留为 deprecation shim 直到
  Phase 2 sweep 完成
- **`scripted_plan` 接口扩展**：`build_scripted_plan` 增加 `pools: LocationPools`
  参数（home/work/poi 分别传入），plan 生成时按 step.activity 类型从正确 pool 抽
- **新增 reachability 不变量**：所有 agent 的 home/work/POI 之间 SHALL 通过 atlas
  connection 图两两可达；构造时 BFS 校验，失败 fail-fast
- **Non-goals**：
  - 不改 Atlas / Ledger / Engine 内部模型——Atlas 已有需要的数据
  - 不改 NavigationService——其已支持 building 目的地的路由
  - 不改 perception / encounter / metrics 实现——它们对位置 ID 类型不敏感
  - 不引入"家庭"级共享 home（这是 A2 household-coupling change 的范围）

## Capabilities

### New Capabilities

无（沿用现有 atlas / cartography / agent 能力，仅修 wiring）

### Modified Capabilities

- `suite-wiring`: `_pick_connected_destinations` 拆分为 typed pool 采样函数；
  variant suite orchestration SHALL 用三池而非单池构造 agent population
- `agent`: `AgentProfile.home_location` 语义收紧为 residential building；
  `scripted_plan.build_scripted_plan` 接入 `LocationPools` 数据类
- `cartography`: 暴露 `Atlas.list_pois_by_kind()` 和 `Atlas.list_workplaces()`
  两个便利方法（基于已有 `list_buildings_by_type`），让 typed pool 采样代码
  路径直接从 atlas 拿到 categorized buildings 而不重复 building_type 字符串

## Impact

- **代码**：
  - `tools/smoke_experiment_demo.py`（_pick_connected_destinations 改造）
  - `tools/run_variant_suite.py`（消费新 typed pools）
  - `synthetic_socio_wind_tunnel/agent/population.py`（sample_population
    增加 `pools` 参数，home_location 校验来自 home_pool）
  - `synthetic_socio_wind_tunnel/agent/scripted_plan.py`（build_scripted_plan
    增加 `pools` 参数）
  - `synthetic_socio_wind_tunnel/atlas/service.py`（新增两便利方法）
- **测试**：
  - 新增 `tests/test_typed_location_pools.py`：池采样确定性、reachability、
    pool 之间不重叠
  - 修改 `tests/test_life_pattern.py`、`test_agent_population.py`、
    `test_realism_emergence.py`：传 typed pools 而非裸 destinations
- **数据**：
  - D1' / D2 实验数据标 deprecated（不删，保留作对照）
  - 修完后跑 1-seed smoke 写入 `data/experiments/<ts>_d1pp_typed_locations_verify/`，
    验 dwell residential ≥ 40%
- **协议合规**：
  - `experimental-design` spec 的 dwell distribution acceptance criteria
    SHALL 添加"residential ≥ X% / street ≤ Y%"门禁（具体阈值在 design.md 给）
