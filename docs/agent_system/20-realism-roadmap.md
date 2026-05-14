# Realism Roadmap — 让 agent 个体 + 群体行为高保真

> 写于 2026-04-28，回应"产品核心是 agent 拟真度而非 publishable rigor"的
> 重新定位。本文不是 openspec change，是路线图——拆解出 4-5 个独立可
> ship 的 stage，每个 stage 自带产品价值。

---

## 1. "拟真"的精确定义

模糊的"像真人"不可工程化。把它拆成 6 个**可观察的 fidelity 维度**：

### F1 — 时空真实性（spatiotemporal）
- **定义**：在时间 T、地点 L，发生的事跟现实 Lane Cove 在时间 T、地点 L 的事统计上一致
- **可测**：rush hour 形状、cafe 中午高峰、周末公园集中、夜晚活动稀疏
- **现状**：❌ 当前 `scripted_plan` 时间锚点用固定 list 均匀采样；周末 = 工作日；POI 没"热度时段"
- **真实数据 anchor**：ABS Travel Survey OD + Google Popular Times（已有 fetch script，待跑）

### F2 — 个体差异性（heterogeneity）
- **定义**：100 个 agent 给同一刺激，反应分布跟真人群一致（不是均匀，不是单峰）
- **可测**：相同 push 下，不同人格 / 不同 care_hours / 不同 community_tenure 的 agent 行为差异
- **现状**：⚠️ 19 维 calibrated profile 存了，但 `scripted_plan` 只读 2 维（work_mode + home），其它 17 维是装饰
- **要做**：让 plan 生成消费这 17 维（age / family_composition / care_hours / vehicles / personality 8 维 / etc.）

### F3 — 个人 routine 锚定（personal stickiness）
- **定义**：一个 agent 14 天的轨迹**对ta来说**是连贯的——agent A 周三总去 cafe_main，agent B 总走 dalrymple_avenue，**而不是每天重新随机 sample**
- **可测**：能跟踪某个 agent 14 天行为变化曲线，看到"我的 routine"
- **现状**：❌ `build_scripted_plan(profile, ..., date, rng)` 每天传新 rng，**agent 没"自己的"routine**
- **要做**：per-agent life-pattern 锚（commute time / preferred cafe / leisure venue 在 14 天内 sticky；`personality.routine_adherence` 控锁定强度）

### F4 — 感知 grounding（perception-driven）
- **定义**：agent 看见 / 听见的具体场景影响 ta 的下一步决策。"在 cafe_main 看到 3 个邻居在排队 → 我决定换一家"
- **可测**：能给某 agent 在某时刻 dump 出 "ta 看到了什么"，且这个 view 跟 ta 的下一步选择有可解释关联
- **现状**：⚠️ `PerceptionPipeline.render()` 已实现完整（visual / auditory / olfactory filters），`AgentRuntime.build_observer_context()` 已拼装；**但 `scripted_plan` 完全不调它，`Planner.replan` 也不**
- **要做**：把 perception 输出接入 plan 生成（LLM-driven）；或在 scripted 路径加 lightweight perception-gated 决策

### F5 — 注意力 grounding（phone-driven）
- **定义**：agent 收到的具体推送内容 + agent 的 personality 联合决定 ta 是否被"拉走"。两个 agent 收同一推送，外向高 + 新搬来 → 跟去；内向高 + 老居民 → 不动
- **可测**：dump "agent X 看到了什么 push、ta 的 personality + 历史、ta 的反应"
- **现状**：⚠️ `AttentionService` + `FeedItem` + `DigitalProfile` 全部 ship；variant 推送是泛化模板（`hyperlocal_push` 给所有目标推同样东西）；`Planner.replan` 用 personality 但只读 `routine_adherence` 一维
- **要做**：内容个体化（带 agent 的 ethnicity / language / interests context）+ 反应个体化（读 8 维 personality）

### F6 — 群体涌现（emergent collective）
- **定义**：rush hour、weekend cluster、cafe overflow、word-of-mouth 等模式**不是直接编程的**，是从个体规则涌现的
- **可测**：跑 100 agent × 14 day baseline，能在数据里看到 morning peak / 跨家庭联动 / POI 容量饱和效应
- **现状**：⚠️ social-graph 累积层已 ship（2026-05-05；弱关系 / tie strength 现在被持续累积）；household coupling 与 POI capacity 仍未做
- **要做**：household coupling（家人时间联动）→ POI capacity / heat
  （**conversation capability 已 ship 2026-05-05**——信息能跨 hops 传播；LLM dialogue 留 V2）

---

## 2. 现状 vs 目标 速览表

| 维度 | 基础设施 | 实际接入 sim hot path | 数据 ground truth |
|---|---|---|---|
| F1 时空 | 部分（scripted_plan 模板）| ⚠️ 时间均匀；周末缺 | ❌ ABS Travel Survey 未下载、Popular Times 未抓 |
| F2 个体差异 | ✅ 19 维 profile | ❌ 只读 2 维 | ✅ ABS Census 已校准 |
| F3 routine 锚定 | ❌ 每日 fresh rng | ❌ 无锚 | n/a |
| F4 感知 | ✅ PerceptionPipeline | ❌ scripted_plan / replan 都不调 | n/a（atlas 给场景）|
| F5 注意力 | ✅ AttentionService + DigitalProfile | ⚠️ 推送泛化、反应单维 | n/a |
| F6 群体涌现 | ❌ 无 social graph、POI 无容量 | ❌ | n/a |

**核心 finding**：基础设施 70% 都在了，**接入率不到 30%**。我们花精力建大量积木，但没拼起来。

---

## 3. 五阶段路线图

按"产品 ROI / 工时" 排序：

### Stage 0.5 — `fix-population-uses-typed-locations` 🔧 IN-FLIGHT 2026-05-12
**目标**：修 thesis-blocking bug — agent.home_location 落到 residential building，
scripted_plan 走进 cafe / shop / office 而非街段。

- 旧 wiring：`_pick_connected_destinations(atlas)` 只从 outdoor_areas 抽 →
  agent 14 天 dwell 93% 在 street、0% 在 residential
- 新 wiring：`build_location_pools(atlas)` 按 atlas building_type / area_type
  返回 typed `LocationPools(home_pool / work_pool / poi_pool)`；agent 工厂 +
  scripted_plan + variant stub 全部消费 typed pools
- 1-day smoke ACCEPTANCE：residential ≥ 40% / street ≤ 20% PASS（60.1% / 0%）

**视觉/产品验收**：
- 3D dashboard hex 密度柱出现在 residential 建筑顶上而非街段
- agent X 的 routine 图能区分"在家"vs"在街上"

### Stage 1 — `realism-time-and-self` ✅ ARCHIVED 2026-04-28
**目标**：F1 + F3 — 时空真实 + 个人 routine 锚定

- Popular Times 真抓 + 接入（destination 加权采样按当前小时热度）
- weekday/weekend day-shape 分支
- per-agent life-pattern anchor（commute time / preferred cafe / leisure venue 14 天 sticky；routine_adherence 调强弱）
- `scripted_plan` 读 8 个新维度（age / family_composition / care_hours / vehicles / 4 个 personality）

**视觉/产品验收**：
- 跑 baseline → encounter density 时间序列出现 morning peak
- agent X 的 14 天轨迹能可视化为"我的 routine"图
- 周末 vs 工作日明显不同 shape

### Stage 2 — `realism-perception-loop`（~1-2 周）
**目标**：F4 — 感知 grounding 接入决策回路

- `Planner.generate_daily_plan` prompt 新增 perception block（"今早从家窗看见..."）
- 当 LLM 路径触发时，在 prompt 里展示 SubjectiveView 简版
- protagonist agent（10 个 Sonnet 档）真用上 perception；Haiku 档用 lightweight rule（"看到 cafe_main 排队人 > 5 → 换 destination"）
- 加一个"agent X 现在看到什么"的 inspector tool（debug + 产品页面用）

**视觉/产品验收**：
- 案例页面能点 agent X 看 ta 当前 SubjectiveView（窗外 / 街角 / cafe 内）
- LLM-generated narrative 引用具体场景元素（"过了图书馆门口"）

### Stage 3 — `realism-attention-rebalance` ✅ ARCHIVED 2026-04-29
**目标重构**：F5 第一阶段——把 push 从"打断式中心事件"改为"context 中可被权衡的一个信号"

> **原 Stage 3 范围（"推送内容 + 反应都个体化"）已在 2026-04-29 重构**。
> 在做"推送内容个体化"之前，先把 prompt 结构 + 决策门控调整到合理。
> 否则即使 push 内容个体化，仍然是 100% 触发率 × 个体化内容 = 仍不真实。

实际做了：

- `_build_replan_prompt` 改为对称 context window（push 不被语言学特殊化为"打断者"）
- `should_replan` 6 维 personality + context modifier + 疲劳衰减 + 概率门（取代单维硬阈值）
- `MemoryService.process_tick` 装配 5 字段 interrupt_ctx（current_step / location_kind / nearby_agents 等）
- `replan_decision_log` 可追溯每次决策的入参 + 阈值
- 触发率落入 goldilocks band [5%, 15%]；100 agent 同 push 的响应分布出现 ≥ 3 个聚类

**Stage 3.5 ✅ ARCHIVED 2026-05-08（push-content-individualization）**：
- ✅ variant 推送 FeedItem 携带 agent context（5 audience tags + audience-aware content variants）
- ✅ "感染力衰减" via PushPersonalizer.relevance + urgency modulation
- ✅ inspector payload 含 audience_tag_by_inspected_agent
- 仍待 V2：LLM 生成内容 / 个体化 timing / 多语言 LLM 翻译

**视觉/产品验收**：
- 案例页面 phone mock-up 显示 agent X 收到的真 push（不是泛化文案）
- 同一 push 给 100 agent，反应分布按 personality 8 维聚类成多峰（**已通过 attention-rebalance 实现**）

### Stage 4 — `realism-household-coupling`（~1-2 周）
**目标**：F6 浅层 — 家庭内时间联动

- 同 home_location + family_with_kids 的 agent group 视为 household
- 父母 7am 出门 → 同 household 的 child agent 8am 离家（学校 commute）
- 18:30 family dinner anchor：同 household 同时回 home_location
- routine_adherence 调强弱

**视觉/产品验收**：
- household 集群能在轨迹动画上一起移动
- baseline encounter 出现"家庭 cluster"模式

### Stage 5 — `realism-poi-capacity-and-spread`（~2 周）
**目标**：F6 深层 — POI 容量 + 社交扩散

- 每个 POI 加 capacity（cafe_main 最多 30 同时 occupancy）
- 满了 → agent 改去候选 POI（按距离 + 热度排序）
- "看到邻居进 cafe → 我也进"的 peer effect rule
- 跑 baseline 能看到 cafe overflow 现象

**视觉/产品验收**：
- 案例页面 POI 显示"实时占用 / 容量"bar
- 高峰时段邻近 cafe 之间发生"agent overflow"现象

### Stage 6 — `agent-stack-aitown-port` ✅ APPLIED 2026-05-09（Phase F 部分 deferred）
**目标**：1:1 复刻 ai-town agent 内涵层 — 反思记忆 + 双向 LLM dialogue + 决策树

注意：**此 stage 不属于上文 5 stage 拟真路线图**（路线图聚焦 routine /
注意力 / POI capacity 等"行为像真人"的拟真维度）；本 stage 解决的是
agent **内涵深度**——只对 10/1000 protagonist 启用，scripted agent 路径
完全不变。两条路径正交：拟真 stage 改的是 990 个 scripted plan 的真实感；
本 stage 改的是 10 个主角的"心智结构"。

落地范围：
- `agent-operations` (新 capability)：PendingOp / OperationPool / handlers
  (do_something / generate_message / remember_conversation)
- `memory` (MODIFIED)：reflection events + ImportanceScorer +
  EmbeddingsCache + retrieval_mode="aitown" (normalize-then-sum,
  0.99^hour recency)
- `conversation` (MODIFIED)：Dialogue 4-state machine + DialogueService +
  bridge_to_memory_and_propagation 三层 fan-out
- `agent` (MODIFIED)：identity_text/plan_text + ai-town 状态字段 + 6-step
  决策树 step()，使用 `use_aitown_decision_tree` flag 隔离
- orchestrator：`register_on_tick_end_async` 让 OperationPool.process_pending
  挂到 tick 末尾
- metrics：`reflection_count` / `dialogue_count` / `dialogue_avg_length` /
  `op_timeout_count` / `cost_breakdown`
- inspector：`reflection_log` / `dialogue_log` / `op_log` / `cost_summary`
- `tools/tier_llm_factory.py`：sonnet/haiku/nano 路由

**Phase F 残留**（在 archive 前补完）：
- 24.x benchmark 对照（aitown ON vs OFF），需要真 LLM 跑 publishable suite
- 22.2 inspector smoke 跑 6 protag × 3 day，需要真 LLM
- 19.2 把 tier_llm_factory 接入 run_variant_suite/replan_trace/inspector

---

## 4. 第一阶段（Stage 1）展开

`realism-time-and-self` —— 最小可见改进 + 解锁后续 stage：

### 4.1 子任务

**A. Popular Times 实跑**（0.5 day）
- 跑 `tools/fetch_popular_times.py`（需 OUTSCRAPER_API_KEY，free tier 够）
- 提交 `data/calibration/lanecove_popular_times.json` 进 git
- 加单元测试验证 schema

**B. scripted_plan 维度扩展**（1-1.5 day）
- 把现在 4 个 day-shape (`_commute_day` / `_remote_day` / `_shift_day` / `_flexible_day`) 拆出 sub-conditioning：
  - `family_composition == couple_kids_under_15` → 多一个 3pm school pickup step
  - `unpaid_child_care_hours == "30plus"` → errand 时间集中在 9-15 (school hours)
  - `vehicles_at_dwelling == "0"` → commute step 加 train station as via-point
  - `community_tenure == "new_<1yr"` → leisure POI 多样性提高（在探索）
  - `community_tenure == "established_5plus"` → leisure POI sticky 化（routine 强）
  - `personality.routine_adherence > 0.7` → 同 agent 多日重复 leisure venue
- 设计原则：**每个维度只加 1-2 行 conditioning**，不重写整个 day-shape

**C. weekday/weekend 分支**（0.5 day）
- `build_scripted_plan(profile, destinations, date, rng)` 内部：`weekday = date.weekday() < 5`
- 加 `_weekend_day_shape`（同样 4 模式但 commute → leisure shift）
- ABS Travel Survey 数据未到前用合理 prior（Saturday 主要 errand + leisure，Sunday 主要 leisure + family）

**D. per-agent life-pattern anchor**（1-1.5 day）
- 新增 `LifePattern` Pydantic model：
  ```
  preferred_cafe: str
  preferred_leisure_park: str
  morning_commute_minute: int   # offset within 7-9 window
  weekend_outing_destination: str
  ```
- `sample_population` 时为每个 agent 生成 LifePattern（按 routine_adherence 决定锁定强度）
- `build_scripted_plan` 接收 `life_pattern` 参数：
  - routine_adherence > 0.7 → 100% 用 LifePattern.preferred_*
  - routine_adherence 0.4-0.7 → 70% 用，30% 探索
  - routine_adherence < 0.4 → 30% 用，70% 探索

**E. Popular Times 加权采样**（0.5 day）
- `_pick_destination(rng, destinations, *, current_hour, popular_times_data)` 升级
- 时段 t 的 weight = `popular_times[poi][weekday][hour] / 100`（0-100% peak）
- 加单元测试验证：8am cafe 抽中率 > 14am cafe（咖啡馆早高峰）

### 4.2 测试计划

- `tests/test_scripted_plan.py` 扩展：8 个新维度 conditioning 各 1 个 case
- `tests/test_life_pattern.py` 新建：
  - 高 routine_adherence → 同 agent 14 天重复 venue
  - 低 routine_adherence → 同 agent 14 天 venue 多样
  - LifePattern 同 seed 同输出
- `tests/test_realism_emergence.py` 新建：
  - 跑 100 agent × 7 day baseline
  - assert encounter time-series 有 morning peak（7-9am 显著高于 12-14pm）
  - assert weekend 与 weekday 总 encounter 数有显著差异
  - assert 有 routine_adherence > 0.7 的 agent 14 天 cafe 重复率 > 60%

### 4.3 视觉验收（不写代码也能看到）

- 跑一次 7-day baseline → 用现有 `tools/visualize_run.py` 出 heatmap
- 应该看到（vs 当前）：
  - **时间序列**：扁平 → 有 7-9am / 17-19pm 双峰
  - **空间 heatmap**：均匀分布 → 商业街 + 学校区在白天显著热
  - **某 agent 14d 轨迹**：看起来像随机游走 → 看起来像"我的 routine 加偶尔偏离"

### 4.4 影响

- `agent` capability spec 加 `LifePattern` requirement
- 不动 `Planner` / `AttentionService` / `Atlas` 公共 API
- 下游 stage 2-5 都受益：感知接入和 household coupling 都依赖"agent 有 routine"

---

## 5. 跨 stage 的产品视觉策略

每个 stage 必须配套**案例页面更新**，否则 invisible work：

| Stage | 案例页面新增 |
|---|---|
| 1. time + self | 时间-encounter 双峰曲线；点 agent 看 14d 轨迹（routine 可见）|
| 2. perception | 点 agent 显示 ta 当前 SubjectiveView（窗外 / 街角文字描述）|
| 3. attention | phone mock-up 显示 ta 这周收到的具体 push |
| 4. household | household cluster 联动动画（爸妈孩子一起出门）|
| 5. POI capacity | POI 占用 bar；高峰 overflow 动画 |

→ 每 ship 一个 stage，案例页面"会动得更像"。

---

## 6. 总工时 vs 当前节奏估算

| Stage | 工程工时 | 数据/外部 |
|---|---|---|
| 1 | 4-5 day | Popular Times 抓（30 min）|
| 2 | 7-10 day | — |
| 3 | 4-5 day | — |
| 4 | 7-10 day | — |
| 5 | 10-14 day | — |

**总计 ~6 周专注工时**。可以按 stage 间隔做（每个 stage 之间穿插 1 个 publishable run / case study 页面更新 / commit），实际日历周期可能 2-3 个月。

---

## 7. Open Questions（决定 Stage 1 范围之前）

1. **Q1**：Popular Times 抓多少 POI？top-20 够，还是 top-50？
   - 倾向：top-20（成本和覆盖均衡；free tier 够）

2. **Q2**：LifePattern 字段以什么粒度？
   - 倾向：4-6 个核心 venue + 2-3 个时间 offset；不要 over-engineer
   - 字段不动 atlas building schema，只是 agent 端缓存

3. **Q3**：weekday/weekend 之外要不要建 holiday？
   - 倾向：先不做（公共假期数据需要外部源；ROI 低）

4. **Q4**：scripted_plan 跟 LLM-driven plan 的关系？
   - 现状：scripted_plan 是 990 个 Haiku 档 default；LLM plan 仅 10 个 Sonnet 主角
   - Stage 1 只动 scripted_plan；Stage 2+ 才动 LLM 路径

5. **Q5**：怎么测"像真人"？
   - 直接质性检查（visualize 看曲线 / 轨迹）
   - 间接量性（rush hour 双峰存在性 / weekend differential / routine repeat 率）
   - face validity（真人评分；已有协议）

---

## 8. 决策点

读完这个 roadmap 后需要你回的：

1. ✅ / ❌ 同意按这 5 stage 顺序推
2. Stage 1 范围：A-E 全做 vs 砍掉哪个
3. 优先级跟现有 publishable 路径的关系：
   - **路径 A**：先打满 5 stage，再回 publishable rigor（产品先；论文跟进）
   - **路径 B**：每 stage 之间穿插 1 个 publishable 更新（产品 + 论文交替）
   - **路径 C**：完全停 publishable 路径（only 产品）
4. 案例页面更新节奏：每 stage 跟着改，还是 5 stage 全完后一次性改？

回答完我就开 Stage 1 的 openspec change。
