## Context

D1' DeepSeek smoke 揭示根因：`tools/smoke_experiment_demo.py::_pick_connected_destinations(atlas, n, rng)`
从 `atlas.region.outdoor_areas` 单池 BFS 采样后，返回的 `tuple[str, ...]` 同时
被三处下游消费：

1. `tools/run_variant_suite.py:482` `target_location = destinations[0]`——variant
   推送目标（这个用法合理，target 本来就是 outdoor POI 类）
2. `tools/run_variant_suite.py:502,512` `home_locations=tuple(destinations)`——
   agent 居住地（**bug 源头**：home 应是 residential building）
3. `synthetic_socio_wind_tunnel/agent/scripted_plan.py:105` `destinations: list[str]`
   作为整日 plan 的目的地池（**bug 源头**：errand/leisure/work/school step 应
   分别从 typed POI / workplace 池抽）

`AgentProfile.home_location` 字段语义在 spec 上已是"agent 的家"——bug 不在 spec
而在采样实现。atlas 早已实现 `list_buildings_by_type` 和
`list_residential_buildings`（`atlas/service.py:125,132`），cartography spec
也契约化了 building_type 枚举与 affordance.capacity。

实验数据后果：14 day × 100 agent 跑出来 dwell 93% 在 street、0% 在 building，
encounter 几乎全部发生在街上，weak tie 形成几乎全部在街上。这与 thesis 假设
"超在地推送把人从屏幕拉回**附近的咖啡馆 / 公园 / 邻居家**"完全脱节——所谓
"附近"在当前模拟里只是另一段街。

**约束**：
- 不重跑 atlas（5722 building / 4257 outdoor / 14903 connection 已可用）
- 不动 Engine / Perception / Encounter 的内部模型（它们对位置 ID 类型不敏感）
- 修完后 D1' 必须重跑验证；D2 publishable 启动前必须 D1' 通过 dwell acceptance

## Goals / Non-Goals

**Goals:**

1. agent.home_location 落到 residential building，**14 天结束时 ≥ 95% agent**
   的 end-of-day location 是 `building_type == "residential"`
2. scripted_plan 整日 dwell 分布大致：residential 40–60% / poi 20–40% /
   work-or-school 10–30% / street 5–20%（剩余比例是通勤过路的街道）
3. 池采样确定性可复现（同 seed → 同 agent home/work/POI 组合）
4. BFS reachability 校验：agent 的 home/work/POI 之间两两可达；失败 fail-fast
5. 池间不重叠：home_pool ∩ work_pool ∩ poi_pool = ∅（防止 cafe 同时被当作工作
   和午餐地点）
6. 现有 test 通过；新增 typed_pool test 通过

**Non-Goals:**

1. 不实现"家庭共享 home"——A2 household-coupling 单独 change
2. 不实现"POI 容量上限"——A3 POI heat 单独 change
3. 不改 D2 协议（仍 15 seed × 14 day × 100 agent × DeepSeek）；只在 D1' 修完
   验证后决定 D2 是否重启
4. 不引入 LLM 决定 home/work 分配；纯 deterministic random.choice + 容量约束
5. 不改 `target_location`（推送目标），它仍来自 POI pool 的特定类型（cafe /
   community / park——community heuristic）

## Decisions

### D1 · pool 设计：三池而非单池

**选**：home_pool / work_pool / poi_pool 三个独立 frozen tuple，每个 agent 从
home_pool 抽一次 home，从 work_pool 抽一次 work（按 work_mode 过滤），
scripted_plan 每个 step 按 activity 类型从合适池抽。

**为什么不是单池 + activity-filter**：单池每次 plan step 都要扫一遍 typed
filter，O(N) 浪费；三池预筛后 O(1) 抽样，确定性也更清晰。

**为什么不是按 step 实时查 atlas**：原子操作太散，且 BFS reachability 在
samplers 一层校验更集中。

### D2 · `LocationPools` 数据类签名

```python
# synthetic_socio_wind_tunnel/agent/location_pools.py（新文件）
@dataclass(frozen=True)
class LocationPools:
    home_pool: tuple[str, ...]      # residential buildings
    work_pool: tuple[str, ...]      # office/school/commercial/community/hospital
    poi_pool: tuple[str, ...]       # cafe/restaurant/shop/park/playground/garden
    target_location: str | None     # variant target (subset of poi_pool)
```

API：

```python
def build_location_pools(
    atlas: Atlas,
    *,
    home_count: int = 40,
    work_count: int = 20,
    poi_count: int = 30,
    rng: random.Random,
) -> LocationPools:
    """采样三池并校验 reachability，pool 间互斥。"""
```

`home_count=40`：100 agent × 平均 2.5 人/家 ≈ 40 户；与未来 A2 household
共享 home 兼容。`work_count=20`：覆盖 office / school / hospital 各几个。
`poi_count=30`：cafe / restaurant / shop / park / community 各 3–5 个。

### D3 · 池采样算法（带容量约束）

home_pool：
1. `atlas.list_residential_buildings()` 拿全部 residential
2. 过滤 `affordance.capacity != None and capacity >= 2`（合理住宅）
3. 从最大连通子图 BFS 取一个种子，BFS 周边 `home_count * 5` 个 candidates
4. `rng.sample(candidates, home_count)`
5. 给每户初始化 `remaining_capacity` 字典，agent 分配 home 时按 weighted
   pick（剩余容量越多越可能被选）

work_pool / poi_pool：同算法，过滤条件不同：
- work：`building_type in {office, school, commercial, community, hospital}`
- poi：`building_type in {cafe, restaurant, shop, bar, entertainment, hotel,
  worship}` + `area_type in {park, playground, garden}`

**为什么 BFS 而非随机**：保证 agent 不会被分到孤岛建筑。Lane Cove atlas 有
14903 connection，BFS 几乎总能找到 200+ 节点的连通分量。

### D4 · scripted_plan 接口变化

```python
# 旧
def build_scripted_plan(
    profile: AgentProfile, destinations: list[str],
    date: date, rng: random.Random,
) -> DailyPlan: ...

# 新
def build_scripted_plan(
    profile: AgentProfile, pools: LocationPools,
    date: date, rng: random.Random,
) -> DailyPlan: ...
```

内部 `_pick_destination(rng, pool, exclude)` 现在按调用上下文挑池：

- `_weekday_day_shape` 中 `school_dest` → `pools.work_pool`（学校属 work_pool）
- 早 errand → `pools.poi_pool`（cafe/restaurant/shop）
- 午餐 → `pools.poi_pool`（cafe/restaurant 子集）
- 晚 outing → `pools.poi_pool`
- 通勤回家 → `profile.home_location`
- 留家 → `profile.home_location`

**未传 pools 的旧路径**：deprecation——`destinations: list[str]` 仍接受，
内部 wrap 为 `LocationPools(home_pool=(), work_pool=(),
poi_pool=tuple(destinations), target_location=None)` 并 emit DeprecationWarning。
Phase 2 sweep 完成后下版本删除。

### D5 · `sample_population` 参数变化

```python
# 旧
def sample_population(
    profile: PopulationProfile, *, seed: int, num_protagonists: int = 0,
    home_locations: tuple[str, ...] | None = None,
    generate_identity: bool = False, llm_client=None, identity_model: str = "",
) -> list[AgentProfile]: ...

# 新（保留旧签名兼容）
def sample_population(
    profile: PopulationProfile, *, seed: int, num_protagonists: int = 0,
    pools: LocationPools | None = None,
    home_locations: tuple[str, ...] | None = None,  # deprecated
    generate_identity: bool = False, llm_client=None, identity_model: str = "",
) -> list[AgentProfile]: ...
```

行为：
- `pools is not None`：每个 agent 从 `pools.home_pool` 按 weighted capacity
  抽 home_location；从 `pools.work_pool` 按 profile.work_mode 抽（retired/
  unemployed → workplace = None）
- `pools is None and home_locations is not None`：deprecation 路径，旧行为
  保留
- 两者都 None：raise（与旧逻辑一致）

### D6 · 不变量校验时机

`build_location_pools` 出口前 SHALL：
1. assert `len(home_pool) >= home_count` 且 `len(work_pool) >= work_count`
   且 `len(poi_pool) >= poi_count`
2. assert 三池 disjoint（id 不重复）
3. assert 三池所有 id 都在同一 atlas connection 连通分量内（BFS 一次）
4. 失败 raise `LocationPoolError`，调用方 fail-fast，不退化

`sample_population` 接收 pools 后 assert profile.size ≤ home_pool 总容量。

### D7 · dwell acceptance criteria

D1' 重跑验证脚本 `tools/audit_dwell_distribution.py`（新增）SHALL：
1. 加载 suite 的 baseline seed
2. 计算 `space_activation` 各类型占比
3. assert residential ≥ 40%、street ≤ 20%；不通过 exit 2

阈值是 Lane Cove ABS 时间使用调查的合理估计（人 1 天 24 小时里大约
8h 睡眠 + 8h 在家活动 = 16h ≈ 67% in residential，1–2h 通勤 ≈ 5–8%
in street，剩余在 work/POI）。100 agent × 1 天阈值定 40% / 20% 保守。

## Risks / Trade-offs

- **[全 stack 的 location_id 字符串语义变化]** → home_location 从街段切换到
  building，下游若有 `if home.startswith("road_")` 类隐式假设会失效。Mitigation：
  全仓 grep `home_location` 用法，目前只在 prompt 字符串嵌入和 social_priors
  household_kin 规则使用，都不依赖 id 前缀
- **[agent 大量走向同 building 导致 capacity 冲突]** → 100 agent × 40 home =
  平均 2.5 人/家 OK；但若 capacity 分布偏斜可能挤爆某些大楼。Mitigation：
  weighted pick 时按剩余容量减权，capacity == 0 的从池中剔除
- **[D1' 重跑成本]** → 1 seed × 14 day × 100 agent × DeepSeek 上次 4 hr，这次
  再 4 hr，~$0.30。可接受
- **[scripted_plan 改 pools 接口破现有 test]** → 改 `_DESTS` test fixture 为
  `_POOLS`，集中迁移而非散落。Risk 可控
- **[D2 已 archive 数据失效]** → D2 in-flight 已 kill；之前 archive 的
  20260511_132735_d1_deepseek_nothink_smoke 等数据**保留**作 dwell distribution
  对比基线（"修前 vs 修后"），不删
- **[BFS 校验可能因 atlas 局部不连通而拒绝采样]** → Lane Cove atlas 已被
  cartography enrichment 跑过整体连通性 audit，14903 connection 几乎肯定有
  > 1000 节点的主分量。Mitigation：build_location_pools 失败时 dump 连通分量
  统计到 stderr 供调试

## Migration Plan

1. **Step 1**：新增 `synthetic_socio_wind_tunnel/agent/location_pools.py`
   含 `LocationPools` dataclass + `build_location_pools` 函数
2. **Step 2**：扩 `Atlas.list_pois_by_kind()` 和 `Atlas.list_workplaces()`
3. **Step 3**：`sample_population` 加 `pools` 参数；旧 `home_locations`
   走 deprecation 路径
4. **Step 4**：`scripted_plan.build_scripted_plan` 加 `pools` 参数；旧
   `destinations: list[str]` 走 deprecation
5. **Step 5**：`tools/smoke_experiment_demo.py` 旧 `_pick_connected_destinations`
   保留但加 DeprecationWarning；新增 `_pick_typed_destinations_for_suite()`
6. **Step 6**：`tools/run_variant_suite.py` 切到 `_pick_typed_destinations_for_suite`
   + `LocationPools` + `sample_population(pools=...)` + 传入 scripted_plan
7. **Step 7**：测试通过 → 1-seed smoke 跑 verify suite
8. **Step 8**：`tools/audit_dwell_distribution.py` 跑过 acceptance → archive change

**Rollback**：旧路径保留 deprecation 路径，commit 级 rollback 即可恢复

## Open Questions

- **work_mode → workplace 映射**：retired / unemployed / homemaker 是否要分配
  workplace？目前倾向 None；A2 household-coupling 时再处理。
- **POI 选址加权**：是否要给"近 home 的 POI"加权？短期不做；先看 D1' 重跑数据
  分布再决定。
- **多 building affordance**：若一个 building 同时是 cafe + community + shop，
  归到哪个 pool？倾向 affordance 中第一个 mapped category；不影响 dwell
  acceptance（building 进入即记 building 类，不区分 affordance）。
