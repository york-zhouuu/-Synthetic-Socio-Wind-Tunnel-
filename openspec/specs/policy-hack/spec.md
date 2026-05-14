# policy-hack — 干预变体工具箱

## Purpose

`policy-hack` capability 提供**干预生成器工具箱**：`Variant` 抽象基类 +
`PhaseController` 三段切换 + `VariantRunnerAdapter` runner 挂接辅助 +
4 条 primary variant（A/B/C/D）+ 1 条 paired mirror（A'），让
`experimental-design` spec 冻结的"4 条 rival hypothesis × 14 天协议 + 1
paired mirror"真正能被 `MultiDayRunner` 执行。

与 `multi-day-run` / `attention-channel` / `agent` capability 的关系为
**纯客户端**：不改这些上游的契约，只通过公开 hook（`on_day_start` /
`on_day_end`）和公开 API（`AttentionService.inject_feed_item` / `DigitalProfile`）
施加干预。每条 variant 绑定一个 rival hypothesis（H_info / H_pull /
H_meaning / H_structure），并承诺**零 LLM 调用**——feed 内容由 template +
seed-bound RNG 产生，保证 reproducibility。
## Requirements
### Requirement: Variant 抽象基类

`synthetic_socio_wind_tunnel/policy_hack/base.py` SHALL 定义 `Variant`
为 `pydantic.BaseModel` 与 `abc.ABC` 的混合基类，要求子类提供：

- `name: str`（kebab-case variant id）
- `hypothesis: Literal["H_info", "H_pull", "H_meaning", "H_structure"]`
- `theoretical_lineage: str`（人类可读学派引用）
- `success_criterion: str` / `failure_criterion: str`（弱支持 / 弱证伪判据）
- `chain_position: Literal["algorithmic-input", "attention-main", "spatial-output", "social-downstream"]`
- `is_mirror: bool = False` / `paired_variant: str | None = None`
- `apply_population(profiles, rng) -> list[AgentProfile]`（抽象方法；默认
  返回原 list）
- `apply_day_start(ctx) -> None`（抽象方法；必须实现）
- `apply_day_end(ctx) -> None`（非抽象；默认 no-op）
- `metadata_dict() -> dict`（序列化用，供 MultiDayResult.metadata 消费）

#### Scenario: 子类缺 apply_day_start 无法实例化
- **WHEN** 一个子类继承 `Variant` 但未实现 `apply_day_start`
- **THEN** 实例化该子类 SHALL raise `TypeError`（Python ABC 语义）

#### Scenario: metadata_dict 包含 hypothesis 绑定
- **WHEN** 调用 `variant.metadata_dict()`
- **THEN** 返回 dict SHALL 至少包含键 `name` / `hypothesis` /
  `theoretical_lineage` / `success_criterion` / `failure_criterion` /
  `chain_position` / `is_mirror`；JSON-serializable

### Requirement: PhaseController 三段切换

`PhaseController` SHALL 是 Pydantic frozen model，接收 `baseline_days` /
`intervention_days` / `post_days`（默认 4 / 6 / 4 = 14 天），提供
`phase(day_index) -> Literal["baseline", "intervention", "post"]` 与
`is_active(day_index) -> bool`（iff phase == "intervention"）。

#### Scenario: 默认 14-day 切换
- **WHEN** `PhaseController()` 默认构造，查询 day_index = 0, 3, 4, 9, 10, 13
- **THEN** phase() SHALL 返回 "baseline", "baseline", "intervention",
  "intervention", "post", "post"（边界条件正确）

#### Scenario: is_active 仅在 intervention phase 返回 True
- **WHEN** 调用 `is_active(day_index)` 遍历 0..13
- **THEN** day_index ∈ [4, 9] 返回 True；其它 False

#### Scenario: 自定义 phase 长度
- **WHEN** `PhaseController(baseline_days=1, intervention_days=1, post_days=1)`
- **THEN** day 0 SHALL phase="baseline"；day 1 SHALL phase="intervention"；
  day 2 SHALL phase="post"

### Requirement: VariantRunnerAdapter 挂接 MultiDayRunner

`VariantRunnerAdapter(variant, controller)` SHALL 提供：

- `attach_to(runner: MultiDayRunner) -> None`：注册 `on_day_start` /
  `on_day_end` callback 到 runner；callback 内部构造 `VariantContext` 并
  调用 variant 对应方法，**仅在 intervention phase 调用**
- `setup_run(profiles, rng) -> list[AgentProfile]`：wrapper over
  `variant.apply_population`，返回新 profiles（调用方在构造 orchestrator
  前用）

`VariantContext` frozen dataclass SHALL 至少包含：
- `day_index: int` / `simulated_date: date`
- `phase: Literal["baseline", "intervention", "post"]`
- `ledger: Ledger` / `attention_service: AttentionService | None`
- `runtimes: tuple[AgentRuntime, ...]`
- `rng: Random`（seed-bound，供 variant 取可复现随机数）

#### Scenario: baseline 阶段不触发 apply_day_start
- **WHEN** `VariantRunnerAdapter(variant, controller)` 挂到 runner；
  runner 跑 day 0（baseline）
- **THEN** `variant.apply_day_start` SHALL 不被调用

#### Scenario: intervention 阶段触发 apply_day_start
- **WHEN** runner 跑 day 5（intervention）
- **THEN** `variant.apply_day_start` SHALL 被调用 1 次；传入 ctx 的 phase
  字段为 "intervention"

#### Scenario: setup_run 调用 apply_population
- **WHEN** `adapter.setup_run(initial_profiles, rng)`
- **THEN** 返回的 list 为 `variant.apply_population(initial_profiles, rng)`
  的结果

### Requirement: PushTemplate 数据模型

`synthetic_socio_wind_tunnel/policy_hack/personalizer.py` SHALL 定义 frozen Pydantic `PushTemplate`：

```
template_id: str
topic_id: str                                # cross-recipient 共享 ID（conversation 用它聚合）
base_content: str                            # 含 {location} 等 placeholder
audience_variants: dict[str, str]            # audience_tag → personalized 内容
target_audience_tags: tuple[str, ...]        # 这条 push 的"目标受众"
base_salience: float                         # ∈ [0, 1]
```

- frozen / 不可变
- `audience_variants` 必须包含 `"default"` 键（fallback）
- `target_audience_tags` 必须非空（design D2 + risk R2 强制）；包含至少 1 个非 "default" tag
- `base_salience` ∈ [0, 1]，构造时校验

#### Scenario: 缺少 default 变体抛错

- **WHEN** 构造 `PushTemplate(audience_variants={"parents": "..."}，没有 default)`
- **THEN** 应抛 `ValueError`，明确说明 default 变体必需

#### Scenario: target_audience_tags 必须非空

- **WHEN** 构造 `PushTemplate(target_audience_tags=())`
- **THEN** 应抛 `ValueError`

#### Scenario: 不可变

- **WHEN** 持有实例尝试 `template.template_id = "x"`
- **THEN** 应抛 `FrozenInstanceError` 或 Pydantic ValidationError

### Requirement: PushPersonalizer 服务

`synthetic_socio_wind_tunnel/policy_hack/personalizer.py` SHALL 定义 `PushPersonalizer` 类：

```
audience_tag_for(profile: AgentProfile) -> str       # 5 类规则
relevance(profile: AgentProfile, template: PushTemplate) -> float
personalize(template: PushTemplate, profile: AgentProfile, *,
            location: str, feed_item_id: str, created_at: datetime,
            source: FeedSource, base_urgency: float = 0.6,
            origin_hack_id: str | None = None) -> tuple[FeedItem, float]
```

- `audience_tag_for` 规则（design D3）：
  - `family_composition == "couple_kids_under_15"` → `"parents"`
  - `community_tenure == "new_<1yr"` → `"newcomer"`
  - `age >= 65` 或 `community_tenure == "established_5plus"` → `"elderly"`
  - `age < 30` 且 `household == "single"` → `"young_adult"`
  - 其它 → `"default"`
- `relevance` 计算（design D4）：
  - tag ∈ `target_audience_tags` → 1.0
  - tag == "default" → 0.6
  - 其它 → 0.3
- `personalize` 返回 `(FeedItem, relevance)`：
  - 用 `audience_variants[tag]`（不存在则 fallback 到 `"default"`）渲染 content
  - 渲染时 `{location}` 用传入值替换；缺失 placeholder 静默
  - FeedItem.urgency = `base_urgency × (0.5 + 0.5 × relevance)`
  - FeedItem.topic_id = template.topic_id
  - FeedItem.target_audience_tags = template.target_audience_tags

#### Scenario: parents profile 拿到 parents 变体

- **WHEN** profile.family_composition == "couple_kids_under_15"，调
  `personalize(market_template, profile, location="X")`
- **THEN** 返回 FeedItem.content SHALL 包含 audience_variants["parents"] 的字符串
- **AND** 返回 relevance SHALL 取决于 "parents" 是否 ∈ target_audience_tags

#### Scenario: 未匹配 tag 退到 default

- **WHEN** profile 不命中任何特殊 tag（age=40, single, established=3yr）
- **THEN** audience_tag_for 返回 "default"；personalize 使用 default 变体

#### Scenario: relevance 影响 urgency

- **WHEN** 同一 template + 不同 profile（一个 relevance=1.0，一个 0.3），base_urgency=0.6
- **THEN** 高 relevance agent 的 FeedItem.urgency 应等于 0.6
- **AND** 低 relevance agent 的 FeedItem.urgency 应等于 0.6 × 0.65 = 0.39

#### Scenario: 渲染 location placeholder

- **WHEN** template.audience_variants["default"] == "本街 {location} 有市集"
  调用 personalize(..., location="cafe_main")
- **THEN** FeedItem.content SHALL 含 "cafe_main"，不含 "{location}"

### Requirement: PushTemplate 预设池

`synthetic_socio_wind_tunnel/policy_hack/templates.py` SHALL 提供 5-8 个预设
PushTemplate 实例，覆盖典型 hyperlocal 场景：

- 至少 1 个 "市集 / market" 类（target_audience_tags 含 "parents", "young_adult"）
- 至少 1 个 "读书会 / reading_group" 类（target_audience_tags 含 "elderly", "default"）
- 至少 1 个 "新邻居见面会 / neighbour_meet" 类（target_audience_tags 含 "newcomer"）
- 至少 1 个 "儿童活动 / kid_event" 类（target_audience_tags 含 "parents"）
- 至少 1 个 "社区清理 / community_clean" 类（target_audience_tags 含 "default"）

每个 template 的 audience_variants 必须含 "default"。所有 template 的 base_salience SHALL ∈ [0.6, 0.9]（hyperlocal 范围）。

#### Scenario: 预设池数量

- **WHEN** import `PUSH_TEMPLATES`
- **THEN** SHALL 是 tuple，长度 ∈ [5, 12]

#### Scenario: 每个 template 都通过校验

- **WHEN** 遍历 PUSH_TEMPLATES
- **THEN** 每个 SHALL 是合法 PushTemplate（含 default 变体、非空 target_audience_tags）

### Requirement: HyperlocalPushVariant (A — H_info)

`HyperlocalPushVariant` SHALL 对应 H_info 假设：每日向预定义目标 agent 池
（默认"前一半"agents by agent_id 字典序）推送 hyperlocal feed_items 到指定
target_location。

字段：
- `name = "hyperlocal_push"`, `hypothesis = "H_info"`,
  `chain_position = "algorithmic-input"`
- `target_location: str`（必传，推送指向的 outdoor_area id）
- `target_agent_ids: tuple[str, ...] | None = None`（None = 运行时取前一半）
- `content_templates: tuple[str, ...]`（**legacy fallback**；当 personalizer
  关闭时用）
- `hyperlocal_radius_m: int = 500`
- `daily_push_count: int = 1`
- `use_personalizer: bool = True`（**新增**；True 时走 PushPersonalizer 路径）
- `personalizer: PushPersonalizer | None = None`（可选注入；None 时构造默认实例）

`apply_day_start(ctx)` SHALL 在 intervention 期间：

- 若 `use_personalizer=True`：
  - 从 `policy_hack.templates.PUSH_TEMPLATES` 池中选 `daily_push_count` 个 template（rng-based，本周不重复）
  - 对每个 target agent，调 `personalizer.personalize(template, profile,
    location=target_location, ...)` 生成**个体化** FeedItem
  - 所有 personalized FeedItem 共享同一 `topic_id`（来自 template）
  - 每个 personalized FeedItem 单独 `inject_feed_item(item, [agent_id])`（单 recipient）
- 若 `use_personalizer=False`：
  - 退回 legacy 路径：从 `content_templates` 选一条字符串，broadcast 给所有 target_ids（与本 change 之前的行为一致）

#### Scenario: intervention 期间每日注入

- **WHEN** 用 HyperlocalPushVariant(use_personalizer=True) 跑 6 天 intervention，
  20 target agents
- **THEN** 6 个 intervention day 共注入 6 × 20 = 120 条 personalized FeedItem
- **AND** 每天的 20 条 FeedItem SHALL 共享相同 `topic_id`

#### Scenario: baseline 期间不注入

- **WHEN** 同上
- **THEN** day 0-3（baseline）期间无任何 notification 事件被写入

#### Scenario: legacy fallback 路径

- **WHEN** use_personalizer=False
- **THEN** 行为与 push-content-individualization 之前一致：每天 1 条
  broadcast feed_item，无 topic_id

#### Scenario: 不同 profile 拿到不同 content

- **WHEN** target_ids 包含 1 个 parents profile + 1 个 young_adult profile，
  use_personalizer=True，模板含两种 audience_variants
- **THEN** 这天 inject 的 2 条 FeedItem 的 content SHALL 不同

#### Scenario: 同 topic 共享 topic_id

- **WHEN** 1 天 inject 给 5 agents 共 5 条 personalized FeedItem
- **THEN** 5 条 FeedItem 的 `topic_id` 字段 SHALL 全相同

### Requirement: GlobalDistractionVariant (A' — paired mirror)

`GlobalDistractionVariant` SHALL 对应 H_info 假设的镜像操作：在 intervention
phase 每日饱和推送 global-news 内容（默认 20 条/day）；content 与 hyperlocal
无关；hyperlocal_radius=None；source="global_news"。

`apply_day_start(ctx)` SHALL：
- 在 intervention phase 内每日构造 `daily_push_count` 条 FeedItem，调
  `ctx.attention_service.inject_feed_item(item, target_ids)`

**Stub 操作语义**（fix-variant-measurement-and-friction，2026-05-10）：当 `--use-real-llm` 关闭走 StubReplanLLM 时，本 variant
SHALL 让 stub 返回 `_plan_toward(distraction_destination)` 而不是空 plan
（参见 `suite-wiring` spec 的 StubReplanLLM 修订）。否则 gd 在 stub 路径下
是 operationally inert，不能被作为 paired mirror 使用。

字段：
- `name = "global_distraction"`, `hypothesis = "H_info"`,
  `chain_position = "algorithmic-input"`, `is_mirror = True`,
  `paired_variant = "hyperlocal_push"`
- `target_agent_ids: tuple[str, ...] | None`（默认 None → 选前一半 by agent_id 字典序）
- `content_templates: tuple[str, ...]`（默认 10 条 global news）
- `daily_push_count: int = 20`
- `urgency: float = 0.4`

`metadata_dict()` SHALL 在返回 dict 中包含 `target_agent_ids`（resolved 后的实际集合），让 metric 工厂能据此计算 protag-only `trajectory_deviation_m`。

#### Scenario: 每日推送 20 条（饱和）
- **WHEN** 跑 14 天 GlobalDistractionVariant
- **THEN** intervention 期间每 target agent memory SHALL 累计 6 × 20 =
  120 条 notification events

#### Scenario: 与 A 共享 target_ids 选择逻辑
- **WHEN** A 与 A' 同 seed 跑，目标 agent 池应相同（前一半 by agent_id
  字典序）
- **THEN** A 的 target_ids SHALL == A' 的 target_ids

#### Scenario: gd 注入 feed item 触发 replan
- **WHEN** intervention day 1；50 个 target agent；daily_push_count=20
- **THEN** 当日 attention_service.inject_feed_item SHALL 被调 ≥ 20 次；
  StubReplanLLM(variant_name="global_distraction") 路径下，replan_count SHALL > 0

#### Scenario: gd 与 baseline 在 encounter 上不再 byte-identical
- **WHEN** 1 seed × 14 day × 100 agent，gd vs baseline；StubReplanLLM；
- **THEN** gd 的 encounter_stats.total SHALL ≠ baseline 的 encounter_stats.total
  （不再 byte-identical；具体方向 = "gd 把 target agent 拉向 distraction_destination
   → encounter 模式不同"）

#### Scenario: metadata_dict 输出含 target_agent_ids
- **WHEN** `gd.metadata_dict()`；`gd._resolve_target_ids(runtimes)` 已计算
- **THEN** 返回 dict SHALL 含 `target_agent_ids` 键，值是 tuple[str, ...]

### Requirement: PhoneFrictionVariant (B — H_pull)

`PhoneFrictionVariant` SHALL 对应 H_pull 假设：在 intervention phase 开始
时将每个 agent 的 `DigitalProfile.screen_time_hour` 乘以 `friction_multiplier`
（默认 0.5）；post phase 开始时恢复。同时 SHALL 通过 `attention_service.inject_feed_item`
注入 `friction_nudge` 类型的 trigger event，让 friction 通过
attention → memory → replan 链路真正产生 plan-level 行为差异。

**操作语义升级原因**（fix-variant-measurement-and-friction，2026-05-10）：仅修改 `profile.digital` 在当前 pipeline 下没有 movement
下游 reader（参见 `docs/audit/2026-05-09-bug-hunt.md` B3），导致 pf 与 baseline
全字段 byte-identical。注入 trigger event 让 friction 走 hp 同款的 attention →
replan 因果链路，保持架构一致。

字段：
- `name = "phone_friction"`, `hypothesis = "H_pull"`,
  `chain_position = "attention-main"`
- `friction_multiplier: float = 0.5`（范围 [0.1, 1.0]）
- `nudge_content_templates: tuple[str, ...]` —— 默认 ≥ 3 条 friction nudge 文案
  （如 "今天注意力被屏幕拽走了——出去走走？" / "放下手机，看看附近"）
- `nudge_target_ratio: float = 1.0`（[0.1, 1.0]，默认全员；调试可降）
- `primary_metric_name: str = "encounter.per_day_median"`（contest.json 用此键作 primary）

`apply_intervention_start(ctx)` SHALL：
- 缓存每 agent 原 digital profile；用 `profile.model_copy(update={"digital": DigitalProfile(...)})` 构造新 profile 替换 `agent.runtime.profile`

`apply_day_start(ctx)` SHALL（仅在 intervention phase）：
- 选 `nudge_target_ratio * len(runtimes)` 个 agent（seed-bound 选取，agent_id 字典序）
- 注入 1 条 FeedItem：`source="neighbourhood"`（FeedSource Literal 复用，最贴近"附近邻居"语义）, `category="self_reflection"`, `origin_hack_id="phone_friction"`, `urgency=0.5`, `content` 从 `nudge_content_templates` 中随机选
- attention_service 投递后会被 memory.process_tick 检测，触发 planner.replan

`apply_intervention_end(ctx)` SHALL：
- 第一个 post day：恢复缓存的原 profile

#### Scenario: intervention 第一天应用乘法
- **WHEN** Variant friction_multiplier=0.5；agent 原 screen_time_hour=4.0
- **THEN** intervention day 开始后 agent.profile.digital.screen_time_hour
  SHALL == 2.0

#### Scenario: post phase 恢复
- **WHEN** 进入 post phase 第一天
- **THEN** agent.profile.digital.screen_time_hour SHALL 恢复为 intervention 前的 4.0

#### Scenario: intervention 期 friction nudge 注入触发 replan
- **WHEN** intervention day 1，PhoneFrictionVariant 实例 + 100 agent + StubReplanLLM(variant_name="phone_friction")
- **THEN** attention_service.inject_feed_item SHALL 被调用 ≥ 1 次；
  当日 replan_count SHALL > 0；
  与 baseline 同 seed 同日的 plan 序列在至少一个 agent 上 SHALL 不相等

#### Scenario: nudge_target_ratio 控制注入比例
- **WHEN** PhoneFrictionVariant(nudge_target_ratio=0.3)；100 agent；intervention day 1
- **THEN** 当日恰好 30 个 agent 的 trigger event SHALL 被检测到；其余 70 个 agent SHALL 无 friction trigger

#### Scenario: pf primary metric 不再是 phone_feed_proxy
- **WHEN** PhoneFrictionVariant.primary_metric_name 字段读取
- **THEN** SHALL == "encounter.per_day_median"；contest.json 生成器 SHALL 据此选 primary metric

### Requirement: SharedAnchorVariant (C — H_meaning)

`SharedAnchorVariant` SHALL 对应 H_meaning 假设：在 intervention phase
每日向一组 predefined agents（默认 10% of population，seed-bound 选取）
注入**同一 feed_item_id**的 task-category feed，使这些 agent 共享同一个
"隐藏任务"。

字段：
- `name = "shared_anchor"`, `hypothesis = "H_meaning"`,
  `chain_position = "social-downstream"`
- `share_ratio: float = 0.10`
- `task_templates: tuple[str, ...]`（默认 3-5 个，如 "find the lost cat",
  "spot the street art", "leave a mark on community wall"）

`apply_day_start(ctx)` SHALL：
- 第一个 intervention day：用 ctx.rng 从 task_templates 选 1 个 task
  描述，记入 self._task_description 缓存
- 每个 intervention day：以**同一 feed_item_id**（"shared_anchor_{seed}"）
  注入 feed_item 到选定 agents；category="task"；source="community"

#### Scenario: 10% agents 共享同一 task
- **WHEN** 100 agent population，SharedAnchorVariant(share_ratio=0.10) 跑
- **THEN** intervention 每日有 10 个 agent 收到 task_received event；
  所有 10 个 event 的 feed_item_id SHALL 相同

#### Scenario: task 进入 memory 的 CarryoverContext
- **WHEN** 同上；检查 agents[0] 的 CarryoverContext（day_index=5）
- **THEN** `pending_task_anchors` SHALL 至少包含 1 条对应本 variant 的
  shared task

#### Scenario: Dev mode 3 天压缩仍生效
- **WHEN** PhaseController(1,1,1) + SharedAnchorVariant 跑 3 天
- **THEN** intervention day (day 1) SHALL 注入 1 条 shared task

### Requirement: CatalystSeedingVariant (D — H_structure)

`CatalystSeedingVariant` SHALL 对应 H_structure 假设：在 run 启动前
一次性替换 5% (默认) agent 的 personality 字段为 "connector" 预设
（高 extraversion / 低 routine_adherence / 高 curiosity），其它字段不变。

字段：
- `name = "catalyst_seeding"`, `hypothesis = "H_structure"`,
  `chain_position = "social-downstream"`（结构层改写）
- `catalyst_ratio: float = 0.05`（0.01-0.10）
- `catalyst_personality: PersonalityTraits`（预设高外向 / 低常规 / 高好奇）

`apply_population(profiles, rng)` SHALL：
- 选 `ceil(len(profiles) × catalyst_ratio)` 个 agent（用 rng.sample）
- 对每个选中 agent：`profile.model_copy(update={"personality":
  self.catalyst_personality})` 构造新 profile
- 返回替换后的 profiles list

`apply_day_start` SHALL 是 no-op（本 variant 的作用在 run 前发生）。

#### Scenario: 5% agents 人格被替换
- **WHEN** 100 profiles + CatalystSeedingVariant(catalyst_ratio=0.05) 跑
  apply_population
- **THEN** 返回 list SHALL 有 5 个 agent 的 personality.extraversion 被
  覆盖为 catalyst_personality.extraversion

#### Scenario: 其它字段不变
- **WHEN** 同上
- **THEN** 所有 agent 的 age / occupation / home_location / housing_tenure
  字段 SHALL 与输入相同

### Requirement: CLI dispatch via VARIANTS registry

`policy_hack` 模块 SHALL 暴露 `VARIANTS: dict[str, type[Variant]]` registry；
`tools/run_multi_day_experiment.py` SHALL 在 `--variant <name>` 不为
`baseline` 时通过 registry 实例化 variant、构造 `VariantRunnerAdapter`
挂到 runner；`baseline` 保留为"无 variant 应用"行为。

#### Scenario: variant 名字无效时报错
- **WHEN** `python tools/run_multi_day_experiment.py --variant unknown_xyz`
- **THEN** SHALL exit with error：列出 registry 中所有合法 variant 名字

#### Scenario: baseline 不触发 variant
- **WHEN** `--variant baseline`
- **THEN** 跑 orchestrator + multi-day-runner SHALL 无 variant 参与；行为
  与 multi-day-simulation archive 时一致

### Requirement: 审计翻绿

`synthetic_socio_wind_tunnel.policy_hack` 模块 SHALL importable；
`fitness-audit` 的 `phase2-gaps.policy-hack` 探针 SHALL 自动 PASS。

#### Scenario: policy-hack audit
- **WHEN** 运行 `make fitness-audit`
- **THEN** `phase2-gaps.policy-hack` AuditResult 的 `status` SHALL 为 `pass`

### Requirement: MultiDayResult.metadata 携带 variant 信息

`VariantRunnerAdapter` SHALL 在跑完一个带 variant 的 run 后，让
`MultiDayResult.metadata` dict 至少包含：
- `variant_metadata: dict`（variant.metadata_dict() 的产出）
- `phase_config: dict`（baseline/intervention/post days）
- `seed: int`

以便后续 `metrics` change 从 per-seed result 读取 variant 身份做 contest 分析。

#### Scenario: metadata 序列化完整
- **WHEN** 一个带 variant 的 MultiDayResult 被 `.model_dump()`
- **THEN** 产出的 dict 在 `metadata` key 下 SHALL 含 `variant_metadata` /
  `phase_config` 两个子键

### Requirement: Variant 不触发 LLM 调用

4 条 primary variant + 1 mirror 的所有 apply_* 方法 SHALL **不**调用任何
LLM；feed 内容由 template + seed-bound RNG 产生。

#### Scenario: variant 测试时 LLM 零调用
- **WHEN** 跑 `tests/test_variant_hyperlocal_push.py` 等用 variant 实际
  执行的测试，不 mock LLM
- **THEN** 测试 SHALL 全部通过（证明 variant 不依赖 LLM）

### Requirement: Variant push count SHALL be equalized for paired-mirror

Variant push counts SHALL default to identical values across hp and gd.
To isolate "where pushes point" from "how many pushes happen",
`HyperlocalPushVariant.daily_push_count` and
`GlobalDistractionVariant.daily_push_count` SHALL default to the SAME
value (5). Previously hp had 1/day and gd had 20/day — confounding
direction (local vs distant) with frequency.

`HyperlocalPushVariant.hyperlocal_radius_m` SHALL default to 1000.0 m
(aligned with CLAUDE.md canonical hyperlocal radius), not the legacy 500m.

#### Scenario: hp and gd default to same push count
- **WHEN** `HyperlocalPushVariant()` and `GlobalDistractionVariant()` are
  constructed with defaults
- **THEN** both SHALL have `daily_push_count == 5`

#### Scenario: hp radius aligned with thesis canonical value
- **WHEN** `HyperlocalPushVariant()` is constructed
- **THEN** `instance.hyperlocal_radius_m` SHALL == 1000.0

#### Scenario: explicit override preserved
- **WHEN** `GlobalDistractionVariant(daily_push_count=10)` is constructed
- **THEN** `instance.daily_push_count` SHALL == 10 (override beats default)

