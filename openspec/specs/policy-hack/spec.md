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


### Requirement: HyperlocalPushVariant (A — H_info)

`HyperlocalPushVariant` SHALL 对应 H_info 假设：每日向预定义目标 agent 池
（默认"前一半"agents by agent_id 字典序）推送 1 条 hyperlocal feed_item
到指定 target_location。

字段：
- `name = "hyperlocal_push"`, `hypothesis = "H_info"`,
  `chain_position = "algorithmic-input"`
- `target_location: str`（必传，推送指向的 outdoor_area id）
- `target_agent_ids: tuple[str, ...] | None = None`（None = 运行时取前一半）
- `content_templates: tuple[str, ...]`（默认 3-5 模板）
- `hyperlocal_radius_m: int = 500`
- `daily_push_count: int = 1`

`apply_day_start(ctx)` SHALL 在 intervention 每日选 target agents，调用
`ctx.attention_service.inject_feed_item(feed_item, target_ids)` 一次，
feed_item 用 RNG 从 content_templates 选；category="event"；source="hyperlocal"。

#### Scenario: intervention 期间每日注入一次
- **WHEN** 用 HyperlocalPushVariant 跑 14 天
- **THEN** 6 个 intervention day 每日有 1 条 feed_item 被 inject；目标
  agents 的 memory 应累计 6 条 "notification" kind events

#### Scenario: baseline 期间不注入
- **WHEN** 同上
- **THEN** day 0-3（baseline）期间无任何 notification 事件被写入


### Requirement: GlobalDistractionVariant (A' — paired mirror)

`GlobalDistractionVariant` SHALL 对应 A 的 paired mirror：每日向同一组
target agents 推送大量 global-news 类 feed_item，content 与 hyperlocal
无关。

字段：
- `name = "global_distraction"`, `hypothesis = "H_info"`,
  `is_mirror = True`, `paired_variant = "hyperlocal_push"`
- `content_templates: tuple[str, ...]`（默认全球新闻 3-5 模板）
- `daily_push_count: int = 20`（饱和推送）
- `hyperlocal_radius_m: None = None`（非 hyperlocal）

`apply_day_start(ctx)` SHALL 在 intervention 每日注入 `daily_push_count`
条 feed_item；每条 category="news_global"；source="platform"。

#### Scenario: 每日推送 20 条（饱和）
- **WHEN** 跑 14 天 GlobalDistractionVariant
- **THEN** intervention 期间每 target agent memory SHALL 累计 6 × 20 =
  120 条 notification events

#### Scenario: 与 A 共享 target_ids 选择逻辑
- **WHEN** A 与 A' 同 seed 跑，目标 agent 池应相同（前一半 by agent_id
  字典序）
- **THEN** A 的 target_ids SHALL == A' 的 target_ids


### Requirement: PhoneFrictionVariant (B — H_pull)

`PhoneFrictionVariant` SHALL 对应 H_pull 假设：在 intervention phase 开始
时将每个 agent 的 `DigitalProfile.screen_time_hour` 乘以 `friction_multiplier`
（默认 0.5）；post phase 开始时恢复。

字段：
- `name = "phone_friction"`, `hypothesis = "H_pull"`,
  `chain_position = "attention-main"`
- `friction_multiplier: float = 0.5`（范围 [0.1, 1.0]）

`apply_day_start(ctx)` SHALL：
- 第一个 intervention day（phase 切换点）：缓存每 agent 原 digital profile；
  用 `profile.model_copy(update={"digital": DigitalProfile(...)})` 构造
  新 profile 替换 `agent.runtime.profile`
- 第一个 post day：恢复缓存的原 profile
- 中间天：no-op

#### Scenario: intervention 第一天应用乘法
- **WHEN** Variant friction_multiplier=0.5；agent 原 screen_time_hour=4.0
- **THEN** intervention day 开始后 agent.profile.digital.screen_time_hour
  SHALL == 2.0

#### Scenario: post phase 恢复
- **WHEN** 进入 post phase 第一天
- **THEN** agent.profile.digital.screen_time_hour SHALL 恢复为 intervention
  前的 4.0


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
