## ADDED Requirements

### Requirement: sample_population SHALL enforce age × work_mode bracket constraint

`sample_population` SHALL clamp the work_mode distribution by age bracket
before drawing work_mode. Each age bracket SHALL define an explicit work_mode
sub-distribution that overrides the base distribution:

- age < 16: `{"not_working": 1.0}`
- age 16-21: `{"student": 0.6, "part_time": 0.25, "commute": 0.15}`
- age 22-64: base distribution from `PopulationProfile.work_mode_distribution`
- age 65-74: `{"retired": 0.7, "part_time": 0.2, "not_working": 0.1}`
- age ≥ 75: `{"retired": 0.85, "not_working": 0.15}`

The clamp SHALL be implemented in a helper `_work_mode_distribution_for_age`
that returns a Mapping; this Mapping is then passed to `_weighted_pick`.

#### Scenario: child gets not_working work_mode
- **WHEN** sample_population draws an agent with age=5
- **THEN** work_mode SHALL == "not_working"

#### Scenario: senior gets retired or not_working
- **WHEN** sample_population draws an agent with age=80
- **THEN** work_mode SHALL be in {"retired", "not_working"}

#### Scenario: prime-age agent retains base distribution
- **WHEN** sample_population draws an agent with age=35
- **THEN** work_mode SHALL be drawn from the original
  `PopulationProfile.work_mode_distribution`

### Requirement: sample_population SHALL enforce occupation × (age, work_mode) constraint

The helper `_occupation_for(age, work_mode, rng)` SHALL replace the previous
`_occupation_for(work_mode, rng)`. Occupation candidates SHALL be chosen from
a `(age_bracket, work_mode) → list[str]` lookup. Age brackets: `"<16"`,
`"16-21"`, `"22-64"`, `"65-74"`, `">=75"`.

For example, `("<16", "not_working") → ["student"]`,
`("22-64", "commute") → ["software_dev", "manager", "engineer", "teacher",
"nurse", "doctor", "designer", "consultant", "retail_worker", "construction"]`,
`("65-74", "retired") → ["retired"]`.

#### Scenario: 5-year-old does not get "writer" occupation
- **WHEN** sample_population draws agent age=5, work_mode="not_working"
- **THEN** occupation SHALL be "student" (not "writer" / "software_dev")

#### Scenario: 94-year-old does not get "nurse" occupation
- **WHEN** sample_population draws agent age=94, work_mode="retired"
- **THEN** occupation SHALL be "retired"

#### Scenario: 35-year-old commute gets professional occupation
- **WHEN** sample_population draws agent age=35, work_mode="commute"
- **THEN** occupation SHALL be in {"software_dev", "manager", "engineer",
  "teacher", "nurse", "doctor", "designer", "consultant", "retail_worker",
  "construction"}

### Requirement: sample_population SHALL match workplace to occupation

`sample_population` SHALL filter work_pool by occupation when assigning each
agent's workplace. The function MUST consider both occupation type and home-to-work
distance:

- `teacher` / `tutor` → school subset
- `nurse` / `doctor` → hospital subset
- `software_dev` / `engineer` / `designer` / `writer` / `manager` /
  `consultant` → office subset
- `retail_worker` / `construction` → commercial subset
- `volunteer_coordinator` → community subset
- default → commercial subset

If the filtered subset is empty, fallback SHALL be: office → commercial →
work_pool[0].

The filter SHALL also apply commute radius constraint: among the
occupation-matched subset, only workplaces with center distance ≤
`max_commute_m` (default 1500m) from home_location are eligible. If empty
after radius filter, fallback to closest 5 workplaces in the occupation
subset; if still empty, closest 5 in work_pool.

#### Scenario: teacher works at school
- **WHEN** sample_population produces agent with occupation="teacher",
  work_mode="commute"
- **THEN** profile.workplace SHALL be in pools.work_pool AND
  `atlas.get_building(workplace).building_type` SHALL == "school"

#### Scenario: software_dev works at office not school
- **WHEN** sample_population produces agent with occupation="software_dev",
  work_mode="commute"
- **THEN** profile.workplace.building_type SHALL be "office" (or fallback to
  "commercial" if no office within commute radius)

#### Scenario: workplace within commute radius preferred
- **WHEN** sample_population assigns workplace for an agent at home H
- **THEN** if any occupation-matched workplace exists within 1500m of H,
  the assigned workplace SHALL be one of them

### Requirement: Household clustering SHALL reject high age-gap families

`_cluster_into_households` SHALL refuse to merge an agent into a household
when the resulting `max(ages) - min(ages) > 70`. Such agents SHALL fall back
to a solo household.

This prevents unrealistic groupings like a 92-year-old living with a
newborn in the same dwelling.

#### Scenario: 92 + 0 year old cannot share household
- **WHEN** clustering tries to add a newborn (age=0) into a household
  containing a 92-year-old
- **THEN** clustering SHALL refuse; the newborn SHALL be assigned a solo
  household with its own home_location from the pool

#### Scenario: 70-year-old grandparent + 3-year-old grandchild OK (gap = 67)
- **WHEN** clustering merges a 70-year-old and a 3-year-old into one household
- **THEN** clustering SHALL accept (gap 67 ≤ 70)

## MODIFIED Requirements

### Requirement: build_location_pools SHALL sample typed pools deterministically

The module `synthetic_socio_wind_tunnel.agent.location_pools` SHALL expose a
`build_location_pools(atlas, *, home_count, work_count, poi_count, rng,
quotas=None, n_agents=None, max_commute_m=1500.0)` function.

**New parameters (fix-realism-systemic-gaps, 2026-05-12):**

- `quotas: PoolQuotas | None = None`: typed per-category minimums for
  work_pool and poi_pool. Default `PoolQuotas()` yields:
  - `work: {"office": 4, "school": 6, "commercial": 4, "community": 2, "hospital": 1}` (17 total)
  - `poi: {"food_drink": 8, "shop": 6, "leisure_building": 4, "leisure_outdoor": 12}` (30 total)
- `n_agents: int | None = None`: when given, scales work_count/poi_count by
  `max(quotas_total, n_agents // 5)` so 1000-agent runs don't share 20
  workplaces.

The function MUST:

1. Compute candidate sets per category from atlas
2. For each category in quotas.work, sample its quota size (or all available if
   less). Combine into work_pool. If `work_count > sum(quotas.work)`, top off
   with random extra workplaces from the combined remaining pool
3. Same logic for poi categories (food_drink: cafe + restaurant + bar buildings;
   shop: shop buildings; leisure_building: entertainment + hotel + worship;
   leisure_outdoor: park + playground + garden outdoor areas)
4. Disjoint check (already in spec); reachability check
5. If any quota cannot be fully satisfied (atlas lacks the category),
   log warning + fallback to filling with closest similar category, do NOT
   raise

#### Scenario: quotas guarantee food_drink in poi_pool
- **WHEN** `build_location_pools(atlas, ..., quotas=PoolQuotas())` runs on
  the post-fix Lane Cove atlas (with ≥25 cafes)
- **THEN** `len([p for p in pools.poi_pool if atlas.get_building(p)
  and atlas.get_building(p).building_type in {"cafe","restaurant","bar"}])`
  SHALL be ≥ 8

#### Scenario: school quota respected
- **WHEN** building pools with `quotas=PoolQuotas()`
- **THEN** `len([w for w in pools.work_pool if atlas.get_building(w).building_type
  == "school"])` SHALL be ≤ 7 (quota 6 + 1 top-off slack);
  SHALL be ≥ 4 (atlas has ≥85 schools, quota of 6 achievable)

#### Scenario: n_agents scales pool sizes (capped at atlas availability)
- **WHEN** `build_location_pools(atlas, home_count=500, n_agents=1000, rng=...)`
- **THEN** `len(pools.work_pool)` SHALL be `min(1000 // 5, total_workplaces_in_atlas)`;
  for the Lane Cove atlas (≈160 workplaces) this SHALL be ≥ 100.
  Same cap-at-availability semantics for `pools.poi_pool`. The function
  SHALL log a note to stderr when capping happens but SHALL NOT raise.

### Requirement: scripted_plan 三模式（commute / errand / leisure）

非主角 agent（Haiku tier）的脚本化日程 SHALL 按 `profile.work_mode` 分派
为四类 day-shape（commute / remote / shift / not_working），每类内部
SHALL 至少含三类活动 step：commute、errand、leisure。

时间锚点 SHALL 来自 ABS Travel Survey 2021 Sydney（journey-to-work
departure-time 分布）；errand 与 leisure 目的地 SHALL 按 Popular Times
hourly 热度做加权采样。

`build_scripted_plan(profile, pools, date, rng, atlas)` SHALL 接受
`pools: LocationPools` 与 `atlas: Atlas`（**新增 atlas 参数**用于 school_pickup
解析）；位置 SHALL 在 `synthetic_socio_wind_tunnel.agent.scripted_plan` 模块。

scripted_plan 内部 SHALL：

1. **按 step 类型选池**（fix-population-uses-typed-locations 已规定）：
   - commute → profile.workplace
   - errand → poi_pool food_drink + shop
   - leisure → poi_pool leisure
   - school_dest → `[w for w in pools.work_pool if atlas.get_building(w)
     .building_type == "school"]`（**fix-realism-systemic-gaps**：原本从
     poi_pool 抽，结果 school_pickup 0% 真去 school）
   - 留家 / 晚上回家 → profile.home_location

2. **添加 meal step 模板**（fix-realism-systemic-gaps）：每个 weekday
   day_shape SHALL 含 3 个 meal anchor：
   - breakfast: 7:00-8:00，destination = home_location，duration 15-30 min
   - lunch: 12:00-13:30
     - commute/shift: at workplace 或 workplace-邻近 cafe（rng.random() < 0.4
       概率从 poi food_drink 选最近 cafe；否则 workplace）
     - remote: home_location（rng < 0.2 概率 nearby cafe）
     - not_working/retired: home_location（rng < 0.1 概率 cafe）
   - dinner: 18:00-19:30，destination = home_location（rng < 0.15 概率 restaurant）

3. **按时间排序最终 plan steps**（fix-realism-systemic-gaps）：返回
   DailyPlan 前 SHALL `steps.sort(key=time_key)` 保证 PlanStep 时间单调递增

#### Scenario: commute work_mode 含通勤往返 + errand
- **WHEN** profile.work_mode == "commute"
- **THEN** 返回的 DailyPlan SHALL 含至少 2 个 commute step（home →
  workplace 与 workplace → home）+ ≥ 1 个 errand step + ≥ 1 个 leisure step

#### Scenario: not_working work_mode 无通勤
- **WHEN** profile.work_mode == "not_working"
- **THEN** 返回的 DailyPlan SHALL 不含 commute step；errand / leisure
  step 占满白天

#### Scenario: plan steps 按时间单调递增
- **WHEN** 任意 build_scripted_plan 调用返回 plan
- **THEN** 解析 `[time_key(s.time) for s in plan.steps]` SHALL 等于其自身
  sorted（即时间单调递增）

#### Scenario: 每天 ≥ 3 个 meal step（breakfast/lunch/dinner）
- **WHEN** 任意 weekday plan 生成
- **THEN** plan.steps 含 reason 或 activity 含 "breakfast" / "lunch" /
  "dinner" 的 step 各至少 1 个，共 ≥ 3 个 meal step

#### Scenario: school_pickup 目的地是真 school
- **WHEN** profile.family_composition in ("couple_kids_under_15",
  "one_parent_family") 触发 school_pickup step
- **THEN** step.destination 的 building_type SHALL == "school"（或 fallback
  到 pools.poi_pool[0] 当 work_pool 中无 school）

#### Scenario: 公共签名升级（增 atlas 参数）
- **WHEN** 调用 `build_scripted_plan(profile, date=d, rng=r, pools=p, atlas=a)`
- **THEN** SHALL 不抛；school_pickup 用 atlas 解析；其它行为不变
