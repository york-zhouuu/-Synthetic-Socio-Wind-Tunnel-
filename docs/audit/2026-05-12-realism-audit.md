# 拟真度系统审计 · 2026-05-12

> home_location bug 修完后做的二次审计。在 1 seed × 1 day × 100 agent baseline 上跑了 28 个拟真维度的探针，发现 home_location 远不是唯一的塌方点。本文按严重度排序。

---

## 🚨 SEVERITY 1 · thesis-blocking（必修才能跑 publishable）

### S1.1 · plan step 时间序列乱序（57% agents）

scripted_plan 生成的 PlanStep 列表**时间不单调递增**：

```
样本 (a_42_0000, commute, age=45):
  step 1  8:45  commute to workplace
  step 2  15:00 school pickup
  step 3  18:30 family dinner
  step 4  15:00  errand           ← 早于 step 3
  step 5  17:39  commute home
  step 6  19:00  leisure
  step 7  21:30  rest at home
```

30 个 agent 抽样里 17 个有乱序——57%。

**风险**：orchestrator 按 list order 执行 → agent 18:30 吃完饭又回到 15:00 跑去办事；
或按 time order 执行 → 一些 step 被永远跳过。无论哪种都让 plan "意图"丢失。

**根因**：`_weekday_day_shape` / `_flexible_day` 等组装步骤时按"类别"顺序写入而非时间顺序。
末尾应 `steps.sort(key=lambda s: time_key(s.time))`。

---

### S1.2 · poi_pool 0 cafe / 0 restaurant / 0 bar（"去吃午饭"永远去公园）

poi_pool 30 entries 类型分布：

```
outdoor:playground  16  (53%)
outdoor:park         6  (20%)
shop                 6  (20%)
worship              1   (3%)
hotel                1   (3%)
food_drink           0   (0%)   ← 应该是核心 POI 类
```

所有"errand / lunch / leisure" step 都从 poi_pool 抽，目的地永远不可能是
cafe / restaurant —— 但 cafe 恰是 thesis 测的 "附近社交节点"。

**根因 1**：`build_location_pools` 的 `poi_count=30` 默认值无类别保底。
Lane Cove atlas 总共只有 5 个 cafe+restaurant+bar building（见 S1.5），抽 30 个
按概率 30/5722 命中食饮的期望 << 1。

**根因 2（更严重）**：见 S1.5——atlas 本身只有 5 个食饮 building。

**修法**：build_location_pools 需要"per-category 保底"语义——food_drink 至少 N
个、shop 至少 N 个、leisure-building 至少 N 个、leisure-outdoor 至少 N 个。

---

### S1.3 · work_pool 75% 是 school → 67% agent "在学校上班"

work_pool 20 entries 类型：

```
school        15  (75%)
commercial     3  (15%)
community      1   (5%)
office         1   (5%)
hospital       0
```

random.sample 后，67/100 agent 的 workplace 是 school（**不仅是 teacher**）。

软件工程师在 school 上班、护士在 school 上班、商人在 school 上班——离谱。

**根因 1**：Lane Cove atlas 里 school=85，但 office=8、commercial=4。
random.sample 让 school 占大头。

**根因 2**：`sample_population` 给 agent.workplace 时**不看 occupation**，
随机从整个 work_pool 抽。

**修法**：
- build_location_pools 给 work_pool 加 type 配额（office/school/commercial 各占目标比例）
- sample_population 按 occupation 选 work_pool 子集（teacher → school；engineer →
  office；nurse → hospital；其它 → commercial）

---

### S1.4 · scripted_plan "school pickup" 目的地 0% 是真学校

> "School pickup for kids" step 应该去 school。30 个 agent 抽样里 15 个有 kid step：
> park 5 / playground 6 / shop 3 / hotel 1 / **school 0**。

**根因**：scripted_plan 的 `_pick_destination(rng, pool=poi_pool, ...)` 从 poi_pool 抽——
但 poi_pool 不含 school（school 在 work_pool）。

**修法**：scripted_plan school_dest 应直接从 `work_pool` 选 building_type == "school"
的子集；或拓 `LocationPools` 加 `school_pool` 子字段。

---

### S1.5 · Atlas POI 严重缺料（食饮 5 / 应有 ~50）

Lane Cove atlas 5722 building，按 building_type 统计：

```
residential   5480
school          85
shop            66
utility         57
worship          9
office           8
shop             6
commercial       4
community        3
restaurant       2
cafe             2
worship-misc     2
entertainment    2
industrial       1
bar              1
hotel            1
hospital         1
```

**Lane Cove 实际**（OSM 在线查 + Google Maps 对照）：~25 cafe / ~15 restaurant /
~3-5 bar / ~50 shop。

**根因**：cartography enrichment（Overture/OSM 注入）大量 cafe/restaurant 没被
正确归类——可能落到 `building_type="utility"` 或 `"residential"` 但 affordance
list 含 `eat`/`drink`。

**修法**：审 cartography importer，把"有 eat/drink affordance 的 building"
重映射 building_type → "cafe"/"restaurant"。或直接在 build_location_pools 时
按 affordance 而非 building_type 选 POI。

---

### S1.6 · 1000-agent 下 work_pool=20 hardcoded → 50 人/workplace

scale 投影：1000 agent ÷ 20 workplace = **50 人/workplace**。

实际：小郊区 office 5-30 人 / school 200-500 学生（学生集中可以）/
medical center 5-15 / community center 10-50。

**风险**：每个 workplace 强制 50 agent 共在 → encounter 在 work hot spot 假性放大。

**修法**：`work_count` 应随 `n_agents` 缩放（推荐 `max(40, n_agents // 5)`），
否则 1000-agent run 的 workplace 互动密度远高于 100-agent smoke。

---

## ⚠️ SEVERITY 2 · realism bug（不阻塞但影响可信度）

### S2.1 · 19% 童工（<16 但 commute/remote/shift）+ 6% 老人通勤（≥70 commute/shift）

**根因**：`work_mode_distribution` 与 `age` 独立采样，无 cross-constraint。

**修法**：sample_population 先采 age，再按 age bracket 决定 work_mode pool：
- age < 16 → ("not_working", "student")
- 16 ≤ age < 22 → ("student", "part_time")
- 65 ≤ age < 75 → ("retired", "part_time")
- age ≥ 75 → ("retired", "not_working")

---

### S2.2 · 12% occupation 与年龄不匹配

```
age=5  occupation=writer    work_mode=remote
age=94 occupation=nurse     work_mode=commute
age=3  occupation=software_dev
age=13 occupation=software_dev
```

**根因**：`_occupation_for(work_mode, rng)` 只看 work_mode，不看 age。

**修法**：occupation 选择改为 `(age, work_mode)` 双约束。

---

### S2.3 · commute median 1379m > Lane Cove "hyperlocal" 1000m radius

```
median commute distance: 1379m
max: 3071m, min: 104m
```

agent 通勤距离比 thesis 测的"超在地半径"还远——意味着干预的 1000m 推送可能
打不中 agent 的通勤路径（agent 已经走出 1km 半径）。

**根因**：home_pool 和 work_pool 在 `_largest_connected_component` 里被 BFS
扩散到很远；没有"home ↔ work 距离上限"约束。

**修法**：build_location_pools 加 `max_commute_m=1500` 参数，sample_population
分配 workplace 时按"距 home < max_commute_m"过滤。

---

### S2.4 · 0.2 meals/day · 80% agent 一顿没吃

30 个 agent 抽样里：

```
0 meals/day: 24 agents
1 meal/day:   6 agents
2+ meals:     0 agents
```

scripted_plan 模板根本没有"吃饭"语义——errand/leisure step 名字是"errand /
leisure" 不包含 meal/eat。

**根因**：scripted_plan 4 个 day_shape（commute/remote/shift/not_working）
没有 breakfast/lunch/dinner step 模板。

**修法**：每个 day_shape 加 3 顿饭锚点（早 7:30 home / 午 12:30 office or POI /
晚 18:30 home），destination 按 location 选择（在家吃 vs 在 cafe 吃）。

---

### S2.5 · 6 个家庭 60+ 岁年龄差（婴儿 + 92 岁住一起）

```
home=rv_54 ages: [0, 20, 22, 43, 45, 51, 56, 92]  (8 人挤一栋，从婴儿到 92 岁)
home=building_4528 ages: [10, 10, 47, 52, 59, 74, 82]
home=rv_25 ages: [1, 22, 42, 59, 64]
```

family_composition coherence 不够——8 人无血缘大杂烩同住。

**根因**：`_cluster_into_households` 把 agents 按 family_composition group 但
没看年龄差距是否合理（祖父母 + 父母 + 孩子可以 60 岁差，但 92 岁 + 0 岁同住
通常意味着 4 代同堂——不合理）。

**修法**：household clustering 加约束："最大成员年龄 - 最小成员年龄 ≤ 70"。

---

## ✅ 检查通过的维度（暂可信）

| 维度 | 结果 |
|---|---|
| **夜不归宿**（end_of_day != home_location） | 0/20 (0%) ✓ |
| **夜间活动**（22h-6h 有 move step） | 0/112 (0%) ✓ |
| **protagonist tier**（10 protag = Sonnet） | 10/10 ✓ |
| **weekend ≠ weekday**（Sat 含 commute） | 0/30 (0%) ✓ |
| **destination 都在 atlas** | 169/169 (100%) ✓ |
| **duration sanity**（0min 或 >12h） | 0/169 ✓ |
| **plan 全空率** | 0/30 ✓ |
| **wake time**（首 move > 6h） | 全 8:20-15:00 ✓ |
| **1000-scale 户均人口** | 2.0 vs ABS 2.6 ✓ |
| **路径连贯性**（agent 全日行走总距离） | 7.2km (合理上限) ✓ |
| **lonely kids**（无成人监护住户） | 2/100 (低噪音可接受) |

---

## 处理优先级建议

### 必修才能跑 publishable（S1.x）

```
S1.1  plan step time sort           ~1h  纯代码 fix（sorted by time）
S1.6  work_count scale              ~30min  build_location_pools 加缩放
S1.3  work_pool per-type quota      ~1h  + occupation→workplace mapping
S1.4  school_pickup → real school   ~1h  scripted_plan 用 work_pool[school 子集]
S1.2  poi_pool per-category quota   ~1h  + food_drink 保底（需 S1.5）
S1.5  atlas POI 重映射               ~2h  cartography importer 审 affordance
```

合计 ~6-7h，1-2 个 OpenSpec change 包就能装下。

### Publishable 可放但发版前要补（S2.x）

```
S2.1  age × work_mode cross         ~1h
S2.2  age × occupation cross        ~30min
S2.3  commute radius constraint     ~2h
S2.4  meal steps in scripted_plan   ~2h
S2.5  household age-gap constraint  ~30min
```

合计 ~6h。

### 建议下一步

**最小 publishable 路径**：先修 S1.x 六个 + S2.4（meal）= 一个新 OpenSpec change
`fix-realism-systemic-gaps`，然后重跑 D1' 验证。S2.1/S2.2/S2.3/S2.5 可以在 D2
publishable 后再补。

总工时估 **8-10h** 代码，1 hr 复盘 + 1 个 1-day smoke 再验。

---

## 复盘 · 为什么这些都没在 spec 里抓到

1. **拟真维度散落各 spec**——agent / cartography / scripted_plan 各自只 cover 自己
   的 surface API，没有一个"end-to-end realism contract" spec
2. **acceptance test 太宽**——之前的 test 只看"agent 数对、duration 不为零"，
   不检查"agent 吃饭了吗、孩子去学校了吗"
3. **没有定期跑 audit**——`tools/audit_dwell_distribution.py` 是这次新加的；
   下一步该加 `audit_realism_systemic.py` 把上面 28 个探针固化

下次每次跑 publishable 前 SHALL 跑两个 audit：
- `audit_dwell_distribution.py`（已加）
- `audit_realism_systemic.py`（待加）

---

## 相关文档

- home_location 修复 spec：`openspec/changes/fix-population-uses-typed-locations/`
- 拟真路线图：`docs/agent_system/20-realism-roadmap.md`
- 局限与伦理：`docs/limitations-ethics.md`（已增加旧数据局限段落）
