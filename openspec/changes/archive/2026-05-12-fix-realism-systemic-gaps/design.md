## Context

`fix-population-uses-typed-locations` (2026-05-12) 修了 home_location bug
（agent 现在住在 residential building）。但拟真度系统 audit 暴露了 4 层
cascade bug：

1. **Cartography importer** 误读 Overture POI category 格式 → atlas 只有
   2 cafe / 2 restaurant（应有 ~25/20）
2. **Population sampling** 维度独立采样 → 5 岁 writer / 94 岁 nurse /
   teacher 在 office 上班
3. **LocationPools** 单纯 random sample 无 per-type quotas → poi_pool 0 食饮
4. **scripted_plan** 步骤组装按"类别"非"时间" → 18:30 后跳回 15:00；
   一天 0 顿饭

每层单独看都"接近能用"，但级联起来让模拟离 thesis 想测的"在 cafe 偶遇邻居"
非常远。本 change 在 4 层各加约束，让真实数据（OSM+Overture+ABS Census）
能完整流到 agent 行为里。

**约束**：
- 不重跑 atlas 收集（OSM/Overture data 已 freeze）
- 不改 D2 publishable 协议
- 修完后 audit 工具 SHALL 通过 11 个 acceptance criteria

## Goals / Non-Goals

**Goals:**

1. atlas cafe ≥ 25 / restaurant ≥ 20（cartography 修正后）
2. 1-day baseline smoke 通过 `audit_realism_systemic.py` 全 11 维度 acceptance：
   - plan step time-sorted: 100%
   - poi_pool food_drink 占比 ≥ 20%
   - work_pool school 占比 ≤ 35%
   - "school pickup" 目的地是 school: 100%
   - 0 童工（<16 commute/remote/shift）
   - 0 occupation/age mismatch
   - commute median < 1200m
   - meals/day ≥ 2.5 平均
   - 0 60+ 岁年龄差 household
   - 1000-scale work_count ≥ 100
3. 现有 1300+ tests 全过；新增 ~25 个 test

**Non-Goals:**

1. 不修"天气影响" / "假期效应" / "agent 生病" 等更深维度
2. 不改 attention / encounter / metrics 计算逻辑
3. 不影响 perception pipeline
4. 不强求 agent 都吃午餐——meal step 可被 routine_adherence 概率门控

## Decisions

### D1 · Cartography Overture category 直接 mapping

**问题**：当前 `_OVERTURE_PLACE_PREFIX_TO_TYPE` 用 `ov_place_cat.split(".", 1)[0]`
取 prefix（设计假定 `"eat_and_drink.cafe"`），但实际 Overture data 是
直接 `"cafe"`。

**选**：新增 `_OVERTURE_CATEGORY_TO_TYPE` 完整 mapping（约 30 entries）：

```python
_OVERTURE_CATEGORY_TO_TYPE = {
    "cafe": "cafe", "coffee_shop": "cafe", "tea_room": "cafe",
    "restaurant": "restaurant", "fast_food_restaurant": "restaurant",
    "pizza_place": "restaurant", "japanese_restaurant": "restaurant",
    # ... 完整列表
    "bar": "bar", "pub": "bar", "wine_bar": "bar",
    "shop": "shop", "convenience_store": "shop", "supermarket": "shop",
    "school": "school", "kindergarten": "school", "university": "school",
    "hospital": "hospital", "clinic": "hospital", "pharmacy": "shop",
    "church_cathedral": "worship", "mosque": "worship", "synagogue": "worship",
    "library": "community", "community_centre": "community",
    "office": "office", "real_estate_agent": "office",
    "park": None,  # outdoor, not building
    "playground": None,
}
```

直接 category match 优先于旧 prefix split；prefix split 作 fallback。

**为什么不删旧 prefix split**：保留向后兼容——Overture 未来可能切换数据
格式。两层 try-catch 顺序：direct → prefix → amenity → shop → building。

### D2 · Affordance-aware 二次分类

对已分类为 utility/industrial/residential 的 building，如果其 affordances
含 `category in {cafe, restaurant, bar}`，重映射 building_type 到对应类型。

这处理 "Sake Ichiban 餐厅因 `building: warehouse` 被误归 industrial" 这类
case——OSM building tag 反映物理形态，POI category 反映功能，**功能优先**。

```python
def _maybe_reclassify_from_affordances(
    building_type: str, affordances: tuple,
) -> str:
    if building_type in ("cafe", "restaurant", "bar"):
        return building_type
    poi_categories = {a.description.split("(")[0].strip().lower()
                      for a in affordances if a.activity_type == "visit"}
    if any(cat in poi_categories for cat in ("cafe", "coffee_shop")):
        return "cafe"
    if any(cat in poi_categories for cat in ("restaurant", "japanese_restaurant",
                                              "italian_restaurant", "pizza_place")):
        return "restaurant"
    if any(cat in poi_categories for cat in ("bar", "pub", "wine_bar")):
        return "bar"
    return building_type
```

### D3 · age × work_mode bracket constraint

**选**：在 sample_population 内 age 已采样后，按 bracket clamp work_mode 分布
（不重抽，按 weighted_pick over 子集分布）：

```python
def _work_mode_distribution_for_age(
    age: int, base_dist: Mapping[str, float],
) -> Mapping[str, float]:
    if age < 16:
        return {"not_working": 1.0}  # students/kids
    if age < 22:
        # Mix of student + part-time + small commute
        return {"student": 0.6, "part_time": 0.25, "commute": 0.15}
    if age < 65:
        return base_dist  # 原分布
    if age < 75:
        return {"retired": 0.7, "part_time": 0.2, "not_working": 0.1}
    return {"retired": 0.85, "not_working": 0.15}
```

**为什么不全 rejection sampling**：rejection 会让 RNG 序列不可预测；显式
重 weight 保 determinism。

### D4 · occupation × (age, work_mode) cross-constraint

`_occupation_for(work_mode, rng)` → `_occupation_for(age, work_mode, rng)`：

```python
_OCCUPATION_BY_AGE_MODE = {
    # (age_bracket, work_mode) → occupation candidates
    ("<16", "not_working"): ["student"],
    ("16-21", "student"): ["student"],
    ("16-21", "part_time"): ["retail_worker", "barista", "tutor"],
    ("22-64", "commute"): ["software_dev", "manager", "engineer", "teacher", "nurse", ...],
    ("22-64", "remote"): ["software_dev", "writer", "designer", "consultant", ...],
    ("65-74", "retired"): ["retired"],
    ("65-74", "part_time"): ["consultant", "volunteer_coordinator", "tutor"],
    (">=75", "retired"): ["retired"],
    (">=75", "not_working"): ["retired"],
}
```

### D5 · occupation → workplace_type mapping

在 sample_population 选 workplace 时，先按 occupation 选 work_pool 子集：

```python
_OCCUPATION_TO_WORKPLACE_TYPES = {
    "teacher": ["school"],
    "nurse": ["hospital"],
    "doctor": ["hospital"],
    "software_dev": ["office"],
    "engineer": ["office", "commercial"],
    "writer": ["office"],  # or remote, no workplace
    "manager": ["office", "commercial"],
    "designer": ["office"],
    "consultant": ["office"],
    "retail_worker": ["shop", "commercial"],
    "barista": ["cafe", "restaurant"],  # would need pools.poi_pool, not work_pool
    "construction": ["commercial"],
    "volunteer_coordinator": ["community"],
    "tutor": ["school", "community"],
    # default: ["commercial"]
}
```

如果 occupation 是 `barista`，原则上 workplace 应该是 cafe，但 cafe 在
poi_pool 而不在 work_pool。**简化**：barista/server agent 在新版本里
workplace=None（视为 POI 工作者），下个 change 再加 "POI 工作者" 概念。

### D6 · LocationPools quotas

```python
@dataclass(frozen=True)
class PoolQuotas:
    work: dict[str, int] = field(default_factory=lambda: {
        "office": 4, "school": 6, "commercial": 4,
        "community": 2, "hospital": 1,
    })
    poi: dict[str, int] = field(default_factory=lambda: {
        "food_drink": 8,    # cafe/restaurant/bar
        "shop": 6,
        "leisure_building": 4,  # entertainment/hotel/worship
        "leisure_outdoor": 12,  # park/playground/garden
    })
```

`build_location_pools` 接受 `quotas: PoolQuotas | None = None`：

```python
def build_location_pools(
    atlas, *, home_count, work_count=None, poi_count=None,
    quotas: PoolQuotas | None = None,
    n_agents: int | None = None,
    max_commute_m: float = 1500.0,
    rng,
):
    # If quotas given, sum its values; else fall back to old hard counts.
    # If n_agents given but counts None, scale: home_count = max(40, n_agents // 2),
    # work_count = sum(quotas.work.values()) * max(1, n_agents // 200) ...
```

当 quotas 总和 < requested count 时，从 fallback 池补足；当 atlas 某类型不足
quota 时 log warning + fallback。

### D7 · commute radius constraint

sample_population 选 workplace 时：

```python
def _pick_workplace_near(
    home_id: str, work_pool: tuple[str, ...],
    atlas, max_m: float, rng: random.Random,
) -> str | None:
    home_c = atlas.get_center(home_id)
    if home_c is None: return None
    candidates_within = []
    for wid in work_pool:
        wc = atlas.get_center(wid)
        if wc is None: continue
        d = ((wc.x - home_c.x)**2 + (wc.y - home_c.y)**2) ** 0.5
        if d <= max_m:
            candidates_within.append((d, wid))
    if candidates_within:
        # Pick proportional to inverse distance (closer = higher prob)
        candidates_within.sort()
        # Restrict to closest 60%, then random pick — avoids "always pick closest"
        n = max(1, int(len(candidates_within) * 0.6))
        return rng.choice([w for _, w in candidates_within[:n]])
    # Fallback: closest workplace regardless of max_m
    closest = sorted(
        work_pool,
        key=lambda wid: ((atlas.get_center(wid).x - home_c.x)**2
                         + (atlas.get_center(wid).y - home_c.y)**2),
    )[:5]
    return rng.choice(closest) if closest else None
```

### D8 · scripted_plan 时间排序 + meal steps

返回 DailyPlan 前：

```python
def _sort_by_time(steps: list[PlanStep]) -> list[PlanStep]:
    def time_key(s):
        try:
            h, m = s.time.split(":")
            return int(h) * 60 + int(m)
        except: return 0
    return sorted(steps, key=time_key)
```

每个 day_shape 加 3 个 meal 锚点；具体由 `_add_meals(steps, profile, rng)`
插入：

```python
def _add_meals(profile, rng, weekday_idx):
    # Determines breakfast / lunch / dinner times by profile.work_mode
    # breakfast: 7:00-8:00 home
    # lunch: 12:00-13:30
    #   - commute / shift: at workplace or workplace-adjacent cafe (poi food_drink)
    #   - remote: home or near-home cafe
    #   - others: home
    # dinner: 18:00-19:30 home or eat-out (15% prob from openness)
```

### D9 · school_pickup → real school

`_weekday_day_shape` 在生成 kid step 时：

```python
if profile.family_composition in ("couple_kids_under_15", "one_parent_family"):
    schools_in_work_pool = [
        wid for wid in pools.work_pool
        if (b := atlas.get_building(wid)) and b.building_type == "school"
    ]
    if schools_in_work_pool:
        school_dest = rng.choice(schools_in_work_pool)
    else:
        school_dest = pools.poi_pool[0]  # fallback
```

为此 build_scripted_plan SHALL 接收 atlas 参数（之前不接）。

### D10 · household age-gap constraint

`_cluster_into_households` 在合并 agent 到同 household 前 check：

```python
def _household_compatible(existing: list[AgentProfile], new: AgentProfile) -> bool:
    if not existing: return True
    ages = [p.age for p in existing] + [new.age]
    if max(ages) - min(ages) > 70:
        return False
    return True
```

clustering 失败时 fallback 到给 new agent 单独 household。

## Risks / Trade-offs

- **[atlas 重建工作量]** Lane Cove atlas 需重跑 importer → 几分钟，但要确认旧
  `data/lanecove_atlas.json` 的所有下游消费（test fixtures）兼容。Mitigation：
  在 importer 修后跑 `tests/test_cartography.py` 验旧 fixtures 仍 OK
- **[occupation pool 收紧导致 protag prompt 重复]** age 22-64 的 commute
  agent 现在都从 5-6 个 occupation 抽——但和 ABS Census 仍 marginal compatible
- **[meal step 数量增 → 4 hr DeepSeek 跑变 5-6 hr]** 每天 +3 step × 14 day ×
  100 agent = 4200 step。但 scripted_plan 是 deterministic 不调 LLM，影响仅
  Orchestrator tick 处理时间，估 < 10% wall increase
- **[commute radius 1500m > 1000m hyperlocal]** 仍超过 thesis 半径——但比
  3071m max 改善 50%；Open Question：是否再收紧到 1000m？目前 1500m 留 buffer
  防 atlas 数据点不密
- **[Lane Cove atlas 重建后 score 变化]** 旧 D1' / archive D1 数据无法直接
  对比；保留作 pre-fix baseline 不删

## Migration Plan

1. **Step 1**：cartography importer 修（D1+D2）
2. **Step 2**：重建 atlas `tools/build_lanecove_atlas.py`，跑
   `tests/test_cartography.py` 确认不 regress
3. **Step 3**：population.py + profile.py cross-constraints（D3-D5）
4. **Step 4**：location_pools.py quotas + commute radius（D6+D7）
5. **Step 5**：scripted_plan.py time sort + meals + school_dest（D8+D9）
6. **Step 6**：household.py age gap（D10）
7. **Step 7**：`tools/audit_realism_systemic.py` + tests
8. **Step 8**：1-day smoke + run audit acceptance
9. **Step 9**：archive

## Open Questions

- **commute radius cap**：1500m vs 1000m？1000m 严格符合 thesis hyperlocal
  半径，但 Lane Cove atlas 在某些 home 周围 1km 内 workplace 不足 5 个。
  目前 design 1500m 留 buffer，可调
- **barista / retail_worker workplace**：cafe/shop 在 poi_pool 不在 work_pool。
  本 change workplace=None；下次"POI 工作者"概念引入再修
- **重建 atlas 后旧实验数据怎么标**：限只在 archive 的 limitations-ethics.md
  补一段，不删旧 data
