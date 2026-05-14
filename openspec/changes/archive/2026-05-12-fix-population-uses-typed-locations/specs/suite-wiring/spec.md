## ADDED Requirements

### Requirement: Suite CLI SHALL build typed LocationPools before population sampling

`tools/run_variant_suite.py::run_seed_with_metrics` SHALL 在 sample_population
调用前调 `synthetic_socio_wind_tunnel.agent.location_pools.build_location_pools`
构造 `LocationPools(home_pool, work_pool, poi_pool, target_location)`：

- `home_pool` SHALL 是 `atlas.list_residential_buildings()` 中可达连通子图的
  采样子集，`len(home_pool) >= max(40, n_agents / 2)`
- `work_pool` SHALL 是 `building_type in {office, school, commercial,
  community, hospital}` 的采样子集，`len(work_pool) >= 20`
- `poi_pool` SHALL 是 `building_type in {cafe, restaurant, shop, bar,
  entertainment, hotel, worship}` ∪ `area_type in {park, playground, garden}`
  的采样子集，`len(poi_pool) >= 30`
- 三池 SHALL pairwise disjoint
- `target_location`（variant push target）SHALL 是 `poi_pool` 子集中的一个
  community-heuristic（cafe / park / community），不再是 outdoor street

构造失败 SHALL raise `LocationPoolError`；run_seed_with_metrics SHALL 把 error
直接传播给调用方（不退化、不 fallback 到旧 outdoor-only 行为）。

#### Scenario: Suite 调 build_location_pools 而非 _pick_connected_destinations
- **WHEN** `run_variant_suite.py --seeds 1 --num-days 1 --agents 100` 跑
- **THEN** 调用栈 SHALL 包含 `build_location_pools`；
  返回的 `LocationPools` SHALL 通过类型断言（home_pool 全为 residential
  building，poi_pool 不含 residential，target_location 在 poi_pool 中）

#### Scenario: pool 数量不足时 fail-fast
- **WHEN** 用一个故意小的 atlas（少于 40 residential buildings）调
  `build_location_pools(atlas, home_count=40, ...)`
- **THEN** SHALL raise `LocationPoolError`；suite CLI SHALL exit with
  code != 0；stderr 含 "home_pool insufficient" 字样

### Requirement: target_location SHALL 来自 POI pool 且按 variant 选 community heuristic

variant push target 的 community-heuristic 选择 SHALL：

- `target_location` SHALL 优先选 `poi_pool` 中 `building_type == "community"`
  的建筑；若无，回退到 `building_type == "cafe"`；再回退到 `area_type in
  {park, plaza, community_garden}`；最后回退到 `poi_pool[0]`
- `target_location` SHALL NOT 是 outdoor street（即 `area_type == "street"`
  的 outdoor_area 永不作为 target）

#### Scenario: target 不是街段
- **WHEN** 任意 variant 跑完，dump `extensions.target_location`
- **THEN** `target_location` SHALL 是 building id 或非 street outdoor area；
  SHALL NOT 以 `road_` 或 `seg_` 模式匹配

## MODIFIED Requirements

### Requirement: StubReplanLLM 按 variant_name 分派行为

`tools/suite_stub_llm.py::StubReplanLLM` SHALL 是 `LLMClient` 协议的纯
Python 实现；`__init__(*, seed, variant_name, target_location, atlas, pools)`
接收 variant 身份、目标位置和 typed LocationPools（**取代旧 `destinations`
参数**）；`generate(prompt, *, model)` **忽略 prompt 内容**，按 variant_name
返回预定的 XML plan 片段：

| variant_name | Stub 响应 |
|---|---|
| `hyperlocal_push` | 含 1 条 PlanStep 走向 target_location（action="move"） |
| `global_distraction` | **含 1 条 PlanStep 走向 distraction_destination**（poi_pool 中距 target_location 最远的 POI；fallback `pools.poi_pool[-1]`） |
| `phone_friction` | **含 1 条 PlanStep 走向 community_heuristic**（poi_pool 中 park / community / plaza；fallback `pools.poi_pool[0]`），代表"放下手机回附近" |
| `shared_anchor` | 走向 community heuristic location（park / community 或 `pools.poi_pool[0]`） |
| `catalyst_seeding` / 未知 | `"<plan></plan>"` |

输出 SHALL 是 Planner.replan 可解析的 XML 格式；stub **MUST NOT** 调用任何
外部 LLM / 网络。

**关键变更**（fix-population-uses-typed-locations，2026-05-12）：原 stub
接收 `destinations: tuple[str, ...]` 单池——该池在旧 wiring 下全部是 outdoor
street，结果 stub 把 agent 推到的 distraction / community heuristic 也是
street，与 thesis "把人拉到附近的咖啡馆 / 公园 / 邻居家" 脱节。修订后 stub
接收 typed `pools`，从 `poi_pool` 选 building 类目标。

#### Scenario: hyperlocal_push stub 产出包含 target building
- **WHEN** 构造 `StubReplanLLM(seed=0, variant_name="hyperlocal_push",
  target_location="lane_cove_community_hub", pools=lc_pools)`；调
  `generate("any prompt")`
- **THEN** 返回字符串 SHALL XML-parse 为非空 plan；至少一个 step 的
  `destination == "lane_cove_community_hub"`；该 destination SHALL 在
  `pools.poi_pool` 中；action 包含 "move"

#### Scenario: global_distraction stub 返回非空 distraction plan（POI building）
- **WHEN** 构造 `StubReplanLLM(seed=0, variant_name="global_distraction",
  target_location="cafe_main", atlas=lc_atlas, pools=lc_pools)`；调 `generate`
- **THEN** 返回字符串 SHALL XML-parse 为非空 plan；
  `destination` SHALL 在 `pools.poi_pool` 中且距 cafe_main 距离最远；
  destination SHALL **不等于** `cafe_main`；destination SHALL **不是**
  outdoor street（`area_type != "street"`）

#### Scenario: phone_friction stub 返回 community heuristic
- **WHEN** 构造 `StubReplanLLM(seed=0, variant_name="phone_friction",
  atlas=lc_atlas, pools=lc_pools)`；调 `generate`
- **THEN** 返回字符串 SHALL XML-parse 为非空 plan；
  destination SHALL 是 building_type ∈ {park, community, worship} 或
  area_type ∈ {park, playground, garden} 的 POI（atlas 缺省时 fallback
  `pools.poi_pool[0]`）；SHALL NOT 是 street

#### Scenario: 跨 seed reproducibility
- **WHEN** 两次分别构造同 seed + 同 pools 的 StubReplanLLM；各调 generate 3 次
- **THEN** 两组返回 SHALL byte-equal

### Requirement: 行为差异最小要求

suite-wiring change 的实施结果 SHALL 让以下行为差异在 1 day × 1 seed × 20 agent ×
4 variant smoke 配置下可被 E2E 测试验证：

- `hyperlocal_push.trajectory_deviation_m`（protag-only）SHALL **小于**
  `global_distraction.trajectory_deviation_m`（protag-only）——hp 把 target
  拉向 push location；gd 把 target 拉向相反的 distraction location
- `phone_friction.encounter.per_day_median` SHALL **大于** `baseline.encounter.per_day_median` —— friction 把人推到户外，encounter 提升
- 4 个 variant 的 `encounter_stats.total` SHALL **两两不相等**（不再 byte-identical）
- `hyperlocal_push.replan_count` SHALL > 0，`phone_friction.replan_count` SHALL > 0，`global_distraction.replan_count` SHALL > 0
- `baseline.replan_count` SHALL == 0
- 4 个 variant 各自的 `replan_no_op_count` SHALL 在 stub 路径下 == 0（stub 永不返回空 plan，除 baseline / catalyst_seeding 外）
- **新增**：baseline 跑完后 `space_activation` 的 `building_type ==
  "residential"` 累计 dwell ≥ 全体 dwell 的 40%；`area_type == "street"` 累计
  dwell ≤ 全体 dwell 的 20%

**阈值**：方向正确即可，不做 CI 分离检查——本 change 目标是因果链通 + agent
真有家，严谨 CI 由后续 publishable 30 seed × 14 day 产出。

#### Scenario: E2E 断言 4 variant 行为可区分
- **WHEN** `pytest tests/test_variant_smoke.py::test_four_variants_diverge` 运行（1 day × 1 seed × 20 agent）
- **THEN** 4 个 variant 的 encounter_stats.total SHALL pairwise 不等；
  hp.trajectory_deviation_m < gd.trajectory_deviation_m；
  pf.encounter.per_day_median > baseline.encounter.per_day_median

#### Scenario: dwell 分布通过 acceptance
- **WHEN** `python3 tools/audit_dwell_distribution.py
  data/experiments/<smoke_dir>/variant_baseline` 在 fix 后的 baseline seed
  上跑
- **THEN** SHALL exit with code 0；stdout 含
  `residential_share=0.XX (>=0.40 ✓)` 与 `street_share=0.XX (<=0.20 ✓)`
