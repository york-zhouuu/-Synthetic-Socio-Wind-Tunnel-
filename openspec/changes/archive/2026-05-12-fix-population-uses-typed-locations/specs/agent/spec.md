## ADDED Requirements

### Requirement: LocationPools dataclass MUST encapsulate typed destination pools

`synthetic_socio_wind_tunnel.agent.location_pools.LocationPools` SHALL 是一个
frozen dataclass，含四个字段：

- `home_pool: tuple[str, ...]`：residential building id；agent.home_location
  SHALL 仅从此池抽
- `work_pool: tuple[str, ...]`：office/school/commercial/community/hospital
  building id；agent.workplace 字段 SHALL 仅从此池抽（profile.work_mode 为
  retired/unemployed 时可为 None）
- `poi_pool: tuple[str, ...]`：cafe/restaurant/shop/bar/entertainment/hotel/
  worship building id ∪ park/playground/garden outdoor_area id；scripted_plan
  的 errand/leisure/outing step SHALL 仅从此池抽
- `target_location: str | None`：variant push target，SHALL 是 `poi_pool` 子集
  或 None（baseline 时）

LocationPools SHALL 是不可变；构造后 SHALL 通过 `validate()` 方法校验：
- 三池 pairwise disjoint
- `target_location is None or target_location in poi_pool`
- 所有池 id 在同一 atlas connection 连通分量内

#### Scenario: 构造合法 pools
- **WHEN** `LocationPools(home_pool=("h1","h2"), work_pool=("w1",),
  poi_pool=("p1","p2"), target_location="p1")` 构造后调 `validate(atlas)`
- **THEN** SHALL 不抛；返回该 instance

#### Scenario: 三池重叠时校验失败
- **WHEN** `LocationPools(home_pool=("x",), work_pool=("x",), poi_pool=(),
  target_location=None).validate(atlas)`
- **THEN** SHALL raise `LocationPoolError`；msg 含 "pools overlap"

#### Scenario: target_location 不在 poi_pool 中
- **WHEN** `LocationPools(home_pool=("h1",), work_pool=(), poi_pool=("p1",),
  target_location="external").validate(atlas)`
- **THEN** SHALL raise `LocationPoolError`；msg 含 "target_location not in
  poi_pool"

### Requirement: build_location_pools SHALL sample typed pools deterministically

The module `synthetic_socio_wind_tunnel.agent.location_pools` SHALL expose a
`build_location_pools(atlas, *, home_count, work_count, poi_count, rng)`
function. The function MUST execute these steps in order:

1. 从 atlas connections 计算最大连通子图
2. 在连通子图中按 BFS 从随机种子节点扩展，分别收集：
   - home candidates：`atlas.list_residential_buildings()` ∩ 连通分量
   - work candidates：`atlas.list_buildings_by_type({office, school,
     commercial, community, hospital})` ∩ 连通分量
   - poi candidates：`atlas.list_buildings_by_type({cafe, restaurant, shop,
     bar, entertainment, hotel, worship})` ∪ `area_type ∈ {park, playground,
     garden}` outdoor ∩ 连通分量
3. 各从对应 candidates 中 `rng.sample` `count` 个
4. 三池 disjoint 校验；不通过 retry 至多 5 次
5. 返回 `LocationPools(...)` 实例

任一池不足 `count` SHALL raise `LocationPoolError`，不退化。

#### Scenario: 确定性可复现
- **WHEN** 用同 atlas + 同 seed 两次调 build_location_pools
- **THEN** 两次返回的 LocationPools SHALL 字段 by-id 相等

#### Scenario: residential 不足时 fail-fast
- **WHEN** atlas 中只有 20 个 residential building，调
  `build_location_pools(atlas, home_count=40, ...)`
- **THEN** SHALL raise `LocationPoolError`；msg 含 "home_count=40 exceeds
  available 20"

#### Scenario: 三池在同一连通分量内
- **WHEN** build_location_pools 返回 `pools`
- **THEN** 对 `pools.home_pool + pools.work_pool + pools.poi_pool` 中任意两
  location id `a, b`，atlas connection 图 SHALL 存在 `a → b` 的路径
  （NavigationService.find_route(a, b).success == True）

## MODIFIED Requirements

### Requirement: scripted_plan 三模式（commute / errand / leisure）

非主角 agent（Haiku tier）的脚本化日程 SHALL 按 `profile.work_mode` 分派
为四类 day-shape（commute / remote / shift / not_working），每类内部
SHALL 至少含三类活动 step：commute、errand、leisure。

时间锚点 SHALL 来自 ABS Travel Survey 2021 Sydney（journey-to-work
departure-time 分布）；errand 与 leisure 目的地 SHALL 按 Popular Times
hourly 热度做加权采样。

`build_scripted_plan(profile, pools, date, rng)` SHALL 接受 `pools:
LocationPools`（**取代旧 `destinations: list[str]` 参数**）；位置 SHALL 在
`synthetic_socio_wind_tunnel.agent.scripted_plan` 模块（不再在
`tools/smoke_experiment_demo.py`）。

scripted_plan 内部 SHALL 按 step 类型选池：
- commute step → `profile.home_location` ↔ `profile.workplace`
  （workplace 来自 work_pool）
- errand step → `pools.poi_pool` 中 building_type ∈ {shop, cafe,
  restaurant} 子集
- leisure step → `pools.poi_pool` 中 building_type ∈ {bar, entertainment,
  worship} 或 area_type ∈ {park, garden} 子集
- school_dest（接孩子）→ `pools.work_pool` 中 building_type == "school"
- 留家 / 晚上回家 → `profile.home_location`

**关键变更**（fix-population-uses-typed-locations，2026-05-12）：旧签名
`destinations: list[str]` 是单池——该池在旧 wiring 下全部是 outdoor street
（_pick_connected_destinations 只从 outdoor_areas 选），结果整日 plan 步骤
全部在街段之间，agent 从不进咖啡馆 / 公园 / 学校 / 家。修订后强制 typed
pools，scripted_plan 输出 plan SHALL 真有 building 目的地。

#### Scenario: commute work_mode 含通勤往返 + errand
- **WHEN** profile.work_mode == "commute"
- **THEN** 返回的 DailyPlan SHALL 含至少 2 个 commute step（home →
  workplace 与 workplace → home）+ ≥ 1 个 errand step（去超市 / 接娃 /
  办事）+ ≥ 1 个 leisure step

#### Scenario: not_working work_mode 无通勤
- **WHEN** profile.work_mode == "not_working"
- **THEN** 返回的 DailyPlan SHALL 不含 commute step；errand / leisure
  step 占满白天

#### Scenario: errand step destination 来自 poi_pool 且非街段
- **WHEN** 任意 scripted_plan 跑完，dump DailyPlan
- **THEN** 每个 reason in {errand, leisure, outing, lunch} 的 step 的
  `destination` SHALL 在 `pools.poi_pool` 中；SHALL 不在 outdoor street
  （`area_type != "street"`）

#### Scenario: 公共签名升级（破 旧 destinations 签名）
- **WHEN** 既有调用 `build_scripted_plan(profile, destinations=[...], ...)`
- **THEN** SHALL emit DeprecationWarning；内部 wrap 为
  `LocationPools(home_pool=(), work_pool=(), poi_pool=tuple(destinations),
  target_location=None)`；返回有效 DailyPlan（向后兼容直至下次 sweep）

#### Scenario: 显式 pools 路径
- **WHEN** `build_scripted_plan(profile, pools=lc_pools, date=d, rng=rng)`
- **THEN** SHALL 不 emit DeprecationWarning；返回的 DailyPlan SHALL 每个
  step.destination 都在合适 pool 中

### Requirement: AgentProfile 作为静态身份

`agent.profile.AgentProfile` SHALL 包含：
`agent_id`、`name`、`age`、`occupation`、`household`、`home_location`、
`workplace: str | None`（**新增**）、
`personality_traits: dict[str, float]`、`personality_description: str`、
`preferred_social_size`、`interests`、`languages`、`wake_time`、`sleep_time`、
`is_protagonist: bool`、`base_model: str`。

`home_location` SHALL 是 `building_type == "residential"` 的 building id；
`sample_population` SHALL 校验该不变量，违反时 raise（不退化）。

`workplace` SHALL 是 work_pool 子集或 None；profile.work_mode in
{retired, unemployed, homemaker, not_working} 时 SHALL 为 None；
profile.work_mode in {commute, remote, shift} 时 SHALL 非空。

Profile 在 agent 生命周期内 SHALL 不变；`trait(name, default=0.5)` 用于
安全取值。

**关键变更**（fix-population-uses-typed-locations，2026-05-12）：原
home_location 字段未约束 location 类型，导致 sample_population 在
home_locations 池为 outdoor 时把街段写入 home_location。修订后 home_location
SHALL 是 residential building；同时新增 workplace 字段补齐"工作地"语义。

#### Scenario: 未定义的人格维度
- **WHEN** 查询 `profile.trait("mysticism")` 而 profile 未包含该字段
- **THEN** SHALL 返回默认值 `0.5`

#### Scenario: home_location 必须是 residential building
- **WHEN** 构造 `AgentProfile(home_location="road_5080_seg_1", ...)`（street
  id）随后 `validate_against_atlas(profile, atlas)`
- **THEN** SHALL raise `ValueError`；msg 含 "home_location must be
  residential building"

#### Scenario: retired agent workplace 为 None
- **WHEN** sample_population 给一个 profile.work_mode == "retired" 的 agent
- **THEN** 返回的 profile.workplace SHALL == None

#### Scenario: commute agent workplace 来自 work_pool
- **WHEN** sample_population 给一个 profile.work_mode == "commute" 的 agent，
  pools.work_pool 含 5 个 building
- **THEN** 返回的 profile.workplace SHALL 在 pools.work_pool 中；SHALL 非空
