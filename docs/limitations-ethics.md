# 局限性与伦理边界

> 写于 2026-05-12。本文档汇总项目<strong>不能声称</strong>的事 + 已知偏差源 + 外推风险 + 伦理边界。
> 五幕报告的第 5 幕（Limitations）从这里取素材；答辩 / 审稿防御也用此文档。

---

## 一句话开篇

> Synthetic Socio Wind Tunnel **不是一个预测真实 Lane Cove 居民会怎么做的模型**。
> 它是一个**严格定义的虚拟实验装置**，用 AI 智能体在 1000 米半径的 Lane Cove 街区上跑 14 天的对照试验，
> 让我们能在<u>真实居民身上不可能跑的实验</u>里观察"反向超在地推送"这个干预手段的因果效应。
>
> 跑出的数字是"<strong>这个装置里的 1000 个智能体在这套干预下行为如何变</strong>"，
> **不是**"Lane Cove 真居民会变成什么样"。

---

## 一、Synthetic Agent 不是真人

### 关键事实

- 1000 个 agent 全部由代码 + LLM 生成；**没有任何真实居民的隐私数据**进入模型
- agent 的 19 个属性维度（年龄 / 职业 / 家庭结构 / 工作模式等）按 **ABS 2021 Census SAL12275** 的边缘分布抽样
   ——拿到的是"Lane Cove 整体的人口统计分布"，不是"Lane Cove 真人的具体属性"
- agent 的 identity_text（"我是 42 岁的 Anna，住在 Greenwich……"）是 LLM 基于 archetype 模板生成的，
  和 archetype 描述的真实居民个体没有任何 1:1 对应

### 不能声称的事

- ❌ "Lane Cove 真居民被超在地推送拉到了 cafe"
  → ✅ 应改成："Lane Cove 人口分布下的合成智能体表现出向 cafe 偏移的行为"
- ❌ "Anna 这个例子说明…"
  → ✅ "Anna（一个 ABS Census 分布下的合成 persona）的轨迹显示…"
- ❌ "我们采访了 Lane Cove 居民"
  → ✅ "我们 prompt LLM 生成了基于 Census 分布的合成人物背景"

---

## 二、模型偏见（model bias）的传导

### 风险

LLM 训练数据里携带了大量**社会刻板印象**。当我们让 LLM 给"亚裔通勤白领 Mark"或"退休本地白人 Pam"生成生活故事时，
LLM 会按其训练数据里的统计相关性输出回答。这意味着：

- 老白人 → 偏向"退休 + Bushcare + Cameraygal Festival"叙事
- 年轻华裔 → 偏向"加班 + 兼职刷题 + WeChat 群"叙事

**这些不一定错，但它们是 LLM 的统计先验，不是 Lane Cove 真实多样性**。

### 我们做过的缓解

- **stereotype audit**（swap/blind/cross-model）：在 OpenSpec change `stereotype-audit`（2026-04-27 archive）里实现了
  三种 audit 协议（attribute swap / blind generation / cross-model comparison），但**整套协议在 publishable run 上还没真跑过**
- archetype 模板 + Lane Cove archetype-grounded life history templates（2026-05-10 ship）：让 LLM 在已知 Lane Cove archetype 上变奏，
  而不是从 0 invented stereotype——降低但不消除 bias

### 还应该做但没做的

- ⚠️ stereotype audit 三协议未在 publishable run 跑（一晚一周工时）
- ⚠️ Face validity 问卷（Prolific，5 个 Lane Cove 真居民评分 agent persona 真实度）未做
- ⚠️ Behavioral baseline（Popular Times / ABS Travel Survey）未对照——agent 的 routine 是否匹配真居民未量化

### 不能声称的事

- ❌ "Lane Cove 居民的行为模式是 X"——LLM 给的是 LLM 的 prior
- ❌ "亚裔家庭和白人家庭在干预下反应不同"——可能是真模式，更可能是 LLM 训练数据偏见
- ✅ 应改成："本研究观察到的人口差异 *可能* 反映了 ABS Census 边缘分布 + LLM prior 的联合产物，
   不能孤立解释为社会真实"

---

## 三、单城市外推风险（external validity）

### 关键事实

研究**只在 Lane Cove 上跑了 14 天 × 1000 agent × 1000 米半径**。Lane Cove 是悉尼下北岸的中高密度郊区，
有以下特殊性：

- **人口结构**：35.6% Australian-born / 13.6% England-born / 7.2% China-born / 4.1% Hong Kong-born
  （ABS 2021 SAL12275）——多元但西方主导
- **物理形态**：商业街 Plaza + 周边大量公寓 + 老式 fibro 房子混合
- **公共空间**：Lane Cove National Park + Plaza + 数个小社区中心；街道有底商但小
- **数字化程度**：宽带普及率高，公校 BYOD，老年人 U3A / 图书馆活动多

### 不能外推到的场景

- ❌ "本研究证明超在地推送在全球城市都管用"
   → 不同密度（CBD vs 郊区 vs 农村）、不同文化（西方vs东亚vs南亚）、不同语言生态结果会不同
- ❌ "本研究证明 1000 米是最佳推送半径"
   → 半径效应跟当地步行可达性强相关；上海陆家嘴的 1000 米可能等于 Lane Cove 的 300 米
- ❌ "本研究告诉 Council 该怎么投资基础设施"
   → 这是 thesis 实验装置的结果，不是 Lane Cove Council 政策建议

### 可以小心说的

- ✅ "在 Lane Cove 这样的中高密度、多语言、宽带普及的悉尼郊区里，本研究的合成实验表明…"
- ✅ "本研究的<u>方法学</u>可以推广到其它有 ABS / Census 等价数据的城市（如 Greater Sydney 其它 SAL）"
- ✅ "<u>反向超在地推送作为思想实验</u>可以推广，但 carrying capacity / saturation point 在不同城市需要重测"

---

## 四、统计严谨度的实际限制

### β rigor（统计置信度）

- `experimental-design` spec 把 publishable 的 β rigor 写成了 **≥ 4 seed**
  （30 → 10 (2026-05-17) → 4 (2026-05-18) 务实下调，受单机内存 + Doubao
  单 key 限制）
- **当前 D2 跑 4 seed**，CI 宽度比 30 seed 大约宽 **2.7 倍**
- 后果：
  - hp vs baseline 的 effect size 只能看方向是否显著，**精确量化无意义**
  - 跨变体比较（hp vs pf）的差异需要更宽 CI；只有 effect size 显著大于
    CI 宽度的差异可以引用

### 不能声称的事

- ❌ "hp 让 encounter density 提高了 7.1%"
- ✅ 应改成："hp 在 4-seed × 14-day × 1000-agent Lane Cove 模拟下，median encounter delta = +7.1%（95% CI [+a%, +b%]，n=4，preliminary β=4）"

### 还应该做但没做的

- ⚠️ 30 seed run 未跑（已下调到 β=4 作为新基准 — 详见 `experimental-design` spec）
- ⚠️ 不同 LLM provider 的 cross-validation 未跑（只跑了 Gemini + DeepSeek 各一遍 smoke）
- ⚠️ 不同 random seed pool 的 sensitivity analysis 未跑

---

## 五、智能体内部决策的不可解释性

### 关键事实

agent 的"决定"由 LLM（v4-pro / Gemini Flash）生成的 JSON 输出驱动。我们能记录：

- 推送内容
- 决策结果（"我决定去 cafe_main"）

但**无法访问**：

- LLM 内部的注意力权重 / 神经元激活
- LLM "为什么"决定这么走的因果链
- LLM 输出对小幅 prompt 改动的敏感性（一次性 sampling，没做 ablation）

### 不能声称的事

- ❌ "agent 因为感觉到归属感所以去了 cafe"——这是 LLM 给的<u>合理化叙事</u>，不一定是因果
- ❌ "推送的'本地'属性比'内容相关性'更重要"——需要 prompt ablation 才能拆解
- ✅ 应改成："agent 在收到本地推送时<u>更倾向</u>去推送地，但具体注意力分配机制不可直接观察"

---

## 六、Hybrid 伦理边界

### 项目的 Hybrid 立场

- ✅ **不是真实人群实验**：没有真人参与，没有 IRB
- ⚠️ **但有伦理代价**：LLM 训练数据里的人类偏见可能在 agent 行为里复现，研究的发现可能<u>意外强化</u>对某些群体的刻板印象

### 风险防护机制

- ✅ 不存储任何真实居民数据
- ✅ Stereotype audit 协议已实现（虽未真跑）
- ✅ 文档明确标注"agent 不是真人"
- ✅ 不发布 agent 的 reflection / dialogue 文本作为"Lane Cove 居民观点"
- ⚠️ 答辩 / 论文需要明确：本研究的结论<u>不能</u>被解读为"Lane Cove 真居民如何"

### 对外发布原则

1. 媒体语言：**始终用"合成智能体" / "虚拟居民"**，不用"Lane Cove 居民"
2. 数据公开：seed_*.json / contest.json / 报告 HTML 可公开；agent identity_text 个体不公开（避免被误读为真人引文）
3. 代码开源：✅（系统是研究方法本身的资产）
4. **政策建议**：本研究<u>不</u>直接给 Council 政策建议。如果有人引用，应说明"本研究的方法学可用于评估……，但具体数值结论需要在目标城市本地重做"

---

## 七、技术栈相关披露

### LLM Provider 数据流

- **DeepSeek**（当前 D2 publishable 用）：API 请求经 deepseek.com，提交内容是 agent prompt（含 LLM 生成的 identity_text）
- **Gemini**（D1 用）：API 请求经 Google
- **Anthropic**：暂未在 publishable run 中使用

### 第三方风险

- LLM 提供商**可能记录** prompt / response 用于模型改进（按其 TOS）
- 我们的 prompt 包含合成 agent 个体描述——虽然这些是 LLM 自己生成的，但**对外披露时应说明** "prompt 文本经过 LLM provider 的服务端"

### 缓解

- ⚠️ Provider TOS 检查未做（应在 publishable 发布前检查并文档化）
- ⚠️ 未来如果跑 protected demographics（如 Indigenous 数据）建议本地部署 LLM 以隔离数据

---

## 八、给五幕报告 §5 Limitations 章节的素材清单

写 publishable 报告时，§5 Limitations 应至少覆盖：

1. **Synthetic ≠ real**：第一段强调（§一）
2. **Model bias 未完整 audit**：stereotype audit 协议存在但未真跑（§二）
3. **Single-city external validity 局限**：Lane Cove 特异性（§三）
4. **4 seed β rigor**：spec 务实下调到 4（30 → 10 → 4，截至 2026-05-18），CI 宽度声明（§四）
5. **LLM 决策不可解释**：相关性 ≠ 因果（§五）
6. **DeepSeek/Gemini 数据流披露**：第三方 API 风险（§七）
7. **本研究不直接给政策建议**：方法学贡献 vs 实证发现的区分（§六）

---

## 相关文档

- canonical thesis：`docs/agent_system/00-thesis.md`
- 实验设计契约：`openspec/specs/experimental-design/spec.md`
- 复现性策略：`openspec/specs/validation-strategy/spec.md`
- 公众版项目介绍：`docs/项目产出物.html`
- 四个对照组：`docs/四个对照组.html`
- bug 修复历史：`docs/audit/2026-05-09-bug-hunt.md`

---

## 旧实验数据局限（fix-population-uses-typed-locations 发现）

2026-05-12 审计 D1' DeepSeek smoke 的 `space_activation` 发现 **agent.home_location
是街段而非 residential building** —— `_pick_connected_destinations` 只从
`atlas.region.outdoor_areas` 单池采样，5480 residential building / 5700
建筑↔街道 connection 全部被跳过。后果：

- 100/100 agent 14 天每晚都在街上过夜，0 个进过任何建筑
- dwell 93% on street、7% on playground、0% on residential/cafe/shop/office
- 所有 variant 之间的差异都是发生在 outdoor 街段之间，与 thesis 测的
  "打破附近性盲区"无关

**受影响的归档实验数据**：

- `data/experiments/20260427_*` 系列（D1 Gemini smoke）
- `data/experiments/20260511_132735_d1_deepseek_nothink_smoke/`（D1' DeepSeek smoke）
- 任何 archive 的 publishable / smoke run，在 `fix-population-uses-typed-locations`
  change 修复（2026-05-12）之前的全部 seed JSON

**不应声称**：

- ❌ 旧数据中"hp variant 让 agent 离 push target 更近 N 米"——agent 本来就在
  outdoor 池里，hp / gd 的差异只是不同街段的差异
- ❌ "phone_friction 让 encounter 上升 11%"——基础设施（home, cafe, office）
  完全没生效；上升的偶遇全部发生在街上
- ❌ 把这些数据当作"thesis 已验证"的证据

**应该做的**：

- ✅ 修完后用同一 protocol 重跑 D1'（typed locations 路径）
- ✅ 把旧数据保留作"修前 vs 修后"对照基线，但报告时明确标 `[pre-fix bug]`
- ✅ Publishable run 协议 SHALL 加 `audit_dwell_distribution.py` 作前置 gate

## 九、A/B/C 类系统局限（2026-05-13 系统盘点）

5 个 thesis-critical change 之后再做的"超越代码 bug 层"系统盘点
（`docs/audit/2026-05-12-deep-issues.md`）。

### A 类（已修）

| # | 问题 | 修复 |
|---|---|---|
| A1 | `family_composition` 占位符让 `couple_kids_under_15=49%` 远超 ABS Lane Cove ~22% | 重新校准 `LANE_COVE_PROFILE.family_composition_distribution` 用 ABS 2021 SAL12275 实际值（lone=19%/couple_no_kids=27%/under15=22%/15plus=15%/one_parent=9%/group=5%/other=3%） |
| A2 | 1000 agent + 10 protag 时 90% scripted 不响应 push → 效应稀释 | `run_variant_suite.py` 加 `--num-protagonists` flag；publishable 应 ≥50% Sonnet |
| A3 | 1.4km 大公园里 2 agent 一头一尾仍计 encounter | `noticing_prob(polygon_extent_m=...)` 加空间因子 `min(1, 50m / polygon_extent)` |
| A4 | tie strength 永不衰减 | `SocialGraphService.effective_strength(tie, now_tick)` 用 30 天 half-life 指数衰减；`weak_ties_decayed` / `strong_ties_decayed` 助手 |
| A5 | walking_budget × ai-town LLM 路径未联合验证 | 1-day × 4 variants × `--use-aitown stub` smoke PASS |

### B 类（RESOLVED 6 / disclosed 2）

| # | 问题 | 状态 |
|---|---|---|
| **B1** | ABS 2021 COVID Delta lockdown anomaly（remote=53% 异常） | **RESOLVED**: work_mode 切换 steady-state (commute=59.4/remote=18/shift=12.7/nonworking=9.9)，publishable 报告 disclose de-anomaly |
| **B2** | walking_speed 80/150/250/280 m/min 未实证 calibration | **RESOLVED (citation)**: 在 `agent/population.py` sample_population 速度映射段引用 Austroads 2017 Pedestrian Facility Guideline (80 m/min = 5 km/h walking) + NSW BTS Urban Travel Speeds (250 m/min = 15 km/h congested urban driving)；first-order defensible，未来仍可做 Sydney commute survey |
| **B3** | `BASE_NOTICING_RATE=0.3` invented | **RESOLVED (env override + sensitivity)**: `noticing.py` 用 `SSWT_BASE_NOTICING_RATE` env var 包裹；7 seed × 3d × 100 agent sweep 在 0.2/0.3/0.4 三 rate 下都看到 hyperlocal_push > baseline 方向稳健（tie_count_total_eod delta：+76 / +103 / +74）；docs 标 first-order |
| **B4** | hp 推 1/day vs gd 推 20/day 混"量"和"方向" | **RESOLVED**: 两 variant `daily_push_count=5` 等量；hp `radius` 同时校正到 1000m |
| **B5** | 无 attention fatigue / desensitization | **RESOLVED**: `compute_notification_delta` 加 cumulative `notifications_received_today`，half-life N=8 |
| **B6** | drive-by encounter inflation ~4-10% | **RESOLVED**: noticing gate 加 transit_factor = 1/(1+max_moves/5)；driver tick passing 25 segments 折扣到 0.17 |
| B7 | encounter geographic — A3 + B6 部分覆盖 | A3 fix + B6 fix 部分覆盖；intra-polygon position 仍 0 距离；future: 加 micro-position |
| B8 | `traj_dev` 假设 target 是 outdoor area | RESOLVED in fix-population-uses-typed-locations |

### C 类（RESOLVED 3 / accepted 2）

| # | 问题 | 状态 |
|---|---|---|
| C1 | dialogue 只在 ai-town path 触发 | accept; publishable 用 ai-town (DeepSeek) |
| **C2** | 儿童 agent 与成人移动自由度一样 | **RESOLVED**: `build_scripted_plan` age<6 强制 stay home；6-12 仅 commute+school |
| **C3** | per-trip mode 选择不建模 | **RESOLVED (short-trip override)**: `_dispatch_move` 加 `prefer_driving and straight_line_m < 500m → agent_speed = 80.0` (走 walking pace)，捕捉 "1-car 户走杂货店但开车上班" 行为；500m 阈值标 first-order，未做敏感度 |
| C4 | LLM 不见 in-flight state | accept; plan-level 决策足够，mid-walk 响应是 future |
| **C5** | 14d × 1000 agent × 15 seed wall time / disk size 未实测 | **RESOLVED (gzip)**: `position_trace.write()` 当 `> 500K changes` 自动写 `.gz` sibling，估 6.6GB raw → ~1GB gzipped；wall time 仍需 publishable 前实测 |

### 额外（aggregator 暴露 thesis-downstream outcome）

`fix-remaining-mechanics` change 还修了一个隐匿 bug：`SuiteAggregate.from_run_metrics`
的 `_extract_scalar_metrics` 没把 `weak_tie_formation_count` 和 per-day
`tie_count_*_eod` 拉到 `per_metric_stats`，导致 thesis 主要 outcome 字段在
`aggregate.json` 永远为空 → B3 sensitivity sweep 无法用聚合数据 cross-rate
对比。修复后 aggregate 直接暴露这些字段。

### 不应声称（thesis 报告写作禁词）

- ❌ "walking_speed 80 m/min 是 Lane Cove 真居民通勤速度" → ✅ "first-order estimate based on standard walking-pace 5 km/h"
- ❌ "tie strength 30 天 half-life 反映真实社交记忆衰减" → ✅ "weak-tie attrition heuristic; not empirically calibrated"
- ❌ "noticing 0.3 base rate 是从认知科学实验校准" → ✅ "ideal-condition street co-presence noticing share, first-order"
- ❌ "1.4km 大公园 noticing 折扣 = 50m / 1400m" → ✅ "linear visual-range vs polygon-extent ratio approximation"

## 文档自身的 changelog

- **2026-05-12 创建**：基于 D1' DeepSeek smoke 完成后的状态。整合了 stereotype-audit / validation-strategy / experimental-design 三个 spec 的 limitations 段落 + 新增 DeepSeek 数据流披露。
- **2026-05-12 更新**：加入 fix-population-uses-typed-locations 发现的旧实验
  数据局限段落（home_location bug）。
- **2026-05-13 更新**：A/B/C 系统局限盘点。A 类 (A1-A5) 全修；B 类
  (B1-B8) disclose；C 类 (C1-C5) accept。
- **2026-05-13 更新（fix-remaining-mechanics）**：B2 citation / B3 env override
  + sensitivity sweep / C3 短途 walk override / C5 trace gzip 全修，状态从
  disclose/accept 升级为 RESOLVED；另发现并修复 aggregator 静默丢失
  `weak_tie_formation_count` + `tie_count_*_eod` 的隐匿 bug。
