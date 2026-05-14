## Why

`fix-population-uses-typed-locations` 修完 home_location bug 后，做 28 维度
systemic realism audit 发现还有 **11 个独立 bug**，6 个是 thesis-blocking。
完整审计见 `docs/audit/2026-05-12-realism-audit.md`。

简短总结：

| 严重度 | 问题 | 实测数据 |
|---|---|---|
| 🚨 S1.1 | plan step 时间乱序 | 57% agents（17/30） |
| 🚨 S1.2 | poi_pool **0 cafe / 0 restaurant** | 30 个 POI 里 73% outdoor |
| 🚨 S1.3 | 67% agent "在学校上班" | work_pool 75% school |
| 🚨 S1.4 | "school pickup" 0% 真去 school | 5 park + 6 playground + 0 school |
| 🚨 S1.5 | **Atlas POI 严重缺料** | 5722 building 仅 5 食饮（真 Lane Cove ~50） |
| 🚨 S1.6 | 1000-agent 下 work_count=20 hardcoded | 50 人/办公室 unrealistic |
| ⚠️ S2.1 | 童工 19% / 老人通勤 6% | age × work_mode 独立采样 |
| ⚠️ S2.2 | 12% occupation 与年龄不匹配 | 5 岁 writer / 94 岁 nurse |
| ⚠️ S2.3 | commute median 1379m > 1000m | agent 走出 hyperlocal radius |
| ⚠️ S2.4 | **80% agent 一天不吃饭** | scripted_plan 无 meal 模板 |
| ⚠️ S2.5 | 60+ 岁年龄差同住户 | 0 岁 + 92 岁同住 |

### 根因 cascading：项目其实有"很丰富的人口/POI 数据"，但每个 layer 都丢了一点

1. **OSM + Overture enriched geojson 有 33 cafe / 25 restaurant / 119 食饮**
   → `cartography/importer.py` 的 `_OVERTURE_PLACE_PREFIX_TO_TYPE` 期待
   `"eat_and_drink.cafe"` 前缀格式，但 Overture 数据是直接 `"cafe"`，
   prefix split 后查不到，落入 building tag 路径——"Sake Ichiban" 餐厅
   因 `building: warehouse` 被归类为 utility
2. **atlas 里 cafe 只剩 2 / restaurant 只剩 2** → build_location_pools
   按概率 30/5722 抽 POI，几乎不可能命中食饮
3. **agent.workplace 不看 occupation** → teacher 上 office，nurse 上 school
4. **scripted_plan 步骤组装按"类别"而非按"时间"** → 18:30 后又跳回 15:00
5. **scripted_plan 无 meal step 模板** → 一天 0.2 顿饭

数据其实从 OSM / Overture / ABS Census 都来了——但 4 层 pipeline 每层丢一点，
最后到 agent 行为时只剩"在街上走来走去、从不吃饭、孩子在咖啡馆上班"的乱象。

### 不修的代价

thesis 测的是"**反向超在地推送把人拉回附近的社交节点**"，但当前系统：
- 附近没有食饮节点（atlas 缺料）
- agent 通勤距离超过 hyperlocal 半径（走出测量范围）
- agent 从不吃午饭（社交主场景缺失）
- 学校接娃 0% 去学校（亲属关系节点错位）

publishable run 跑出来的 thesis 结论会被审稿人 1-shot 拆穿。

## What Changes

### Cartography 层

- **修 `_infer_building_type`** SHALL 直接接受 Overture place category
  （"cafe" / "restaurant" / "bar" / "church_cathedral" 等），不再依赖 prefix
  split 格式；新增 `_OVERTURE_CATEGORY_TO_TYPE` 完整 mapping
- **affordance-aware 二次分类**：building 如有 `affordances` 含
  `category in {cafe, restaurant, bar, pub}` 但当前 building_type 不在
  {cafe, restaurant, bar}，SHALL 重映射到对应类型
- **预期效果**：Lane Cove atlas cafe 从 2 → ≥25；restaurant 从 2 → ≥20

### Population 层

- **age × work_mode cross-constraint**：sample_population SHALL 先采 age，
  再按 age bracket 限制 work_mode：
  - age < 16 → ("not_working", "student")
  - 16-21 → ("student", "part_time", "commute")
  - 22-64 → 原分布
  - 65-74 → ("retired", "part_time")
  - ≥75 → ("retired", "not_working")
- **age × occupation cross-constraint**：`_occupation_for` SHALL 按
  (age, work_mode) 选择，不再单按 work_mode
- **occupation × workplace_type cross-constraint**：sample_population 给
  workplace 时 SHALL 按 occupation 选 work_pool 子集
  （teacher → school；nurse/doctor → hospital；engineer/writer/manager → office；
  retail → commercial；其它 → commercial 默认）
- **household age-gap constraint**：`_cluster_into_households` SHALL 拒绝
  最大-最小年龄差 > 70 的 household（避免 0+92 岁同住）

### LocationPools 层

- **per-category quotas in poi_pool**：build_location_pools SHALL 接受
  `poi_quotas: dict[str, int]` 参数；默认值
  `{"food_drink": 8, "shop": 6, "leisure_building": 4, "leisure_outdoor": 12}`
  保证食饮节点不缺位
- **per-category quotas in work_pool**：默认
  `{"office": 4, "school": 6, "commercial": 4, "community": 2, "hospital": 1}`
- **scale-aware `work_count` / `poi_count`**：默认值 SHALL 按
  `max(40, n_agents // 5)` 缩放（旧 hardcoded 20 → 1000-agent 时为 200）
- **commute radius constraint**：sample_population 选 workplace 时 SHALL
  过滤距 home > `max_commute_m=1500` 的 workplace；若过滤后池子为空，按
  距离升序 fallback 到最近的 N 个

### scripted_plan 层

- **按时间排序 plan steps**：build_scripted_plan SHALL 在返回 DailyPlan
  之前 `steps.sort(key=lambda s: time_key(s.time))`
- **meal step 模板**：所有 day_shape 工作日 SHALL 包含三个 meal 锚点
  （早 7:00-8:00 home / 午 12:00-13:00 home-or-poi-or-workplace / 晚 18:00-19:00 home）
- **school_pickup → 真 school**：scripted_plan 在 kid step 时 SHALL 优先从
  work_pool 中 building_type == "school" 子集选 destination（不从 poi_pool）

### 新增 audit 工具

- `tools/audit_realism_systemic.py`：把本 change 修的 11 个维度固化为 audit
  脚本，跑 publishable 前 SHALL 通过

### Non-goals

- 不改 D2 publishable 协议（仍 15 seed × 14 day × 100 agent × DeepSeek）
- 不重跑全部归档实验数据（旧数据保留作 pre-fix baseline 对比）
- 不引入新的 LLM 调用（所有改动都是 deterministic）
- 不实现"agent 生病/请假" / "天气影响活动" / "节假日" 等更深拟真维度——
  本 change 限于 28 维度 audit 暴露的明确 bug

## Capabilities

### New Capabilities

无——本 change 修的都是现有 capability 的 wiring 问题。

### Modified Capabilities

- `cartography`：`_infer_building_type` 接受直接 Overture category；新增
  affordance-aware 二次分类
- `agent`：`sample_population` 引入 age × work_mode × occupation × workplace
  cross-constraints + household age-gap；`build_scripted_plan` 引入 meal
  step + 时间排序 + school_dest 用真 school
- `(LocationPools 部分在 agent spec 下)`：`build_location_pools` 接受 quotas
  参数；默认值按 n_agents 缩放

## Impact

- **代码**：
  - `synthetic_socio_wind_tunnel/cartography/importer.py`（Overture 分类）
  - `synthetic_socio_wind_tunnel/agent/population.py`（cross-constraints）
  - `synthetic_socio_wind_tunnel/agent/profile.py`（occupation→workplace mapping）
  - `synthetic_socio_wind_tunnel/agent/location_pools.py`（quotas）
  - `synthetic_socio_wind_tunnel/agent/scripted_plan.py`（time sort + meal + school_dest）
  - `synthetic_socio_wind_tunnel/agent/household.py`（age-gap clamp）
- **重建 atlas**：`tools/build_lanecove_atlas.py` SHALL rerun 重建 atlas
  以应用新 cartography importer；旧 `data/lanecove_atlas.json` 替换
- **测试**：
  - 新增 `tests/test_cartography_overture_categories.py`
  - 新增 `tests/test_realism_systemic.py`
  - 更新 `tests/test_agent_population.py`（cross-constraints）
  - 更新 `tests/test_scripted_plan.py`（meal + 时间排序）
- **审计**：`tools/audit_realism_systemic.py` 跑 acceptance
- **D1' 重跑触发**：本 change archive 后跑 D1' 1 seed × 14 day × DeepSeek
  作为正式 publishable D2 之前的最终验证
