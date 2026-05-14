## MODIFIED Requirements

### Requirement: PhoneFrictionVariant (B — H_pull)

`PhoneFrictionVariant` SHALL 对应 H_pull 假设：在 intervention phase 开始
时将每个 agent 的 `DigitalProfile.screen_time_hour` 乘以 `friction_multiplier`
（默认 0.5）；post phase 开始时恢复。同时 SHALL 通过 `attention_service.inject_feed_item`
注入 `friction_nudge` 类型的 trigger event，让 friction 通过
attention → memory → replan 链路真正产生 plan-level 行为差异。

**操作语义升级原因**：仅修改 `profile.digital` 在当前 pipeline 下没有 movement
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
- 注入 1 条 FeedItem：`source="phone_friction_nudge"`, `category="self_reflection"`, `urgency=0.5`, `content` 从 `nudge_content_templates` 中随机选
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


### Requirement: GlobalDistractionVariant (A' — paired mirror)

`GlobalDistractionVariant` SHALL 对应 H_info 假设的镜像操作：在 intervention
phase 每日饱和推送 global-news 内容（默认 20 条/day）；content 与 hyperlocal
无关；hyperlocal_radius=None；source="global_news"。

`apply_day_start(ctx)` SHALL：
- 在 intervention phase 内每日构造 `daily_push_count` 条 FeedItem，调
  `ctx.attention_service.inject_feed_item(item, target_ids)`

**Stub 操作语义**：当 `--use-real-llm` 关闭走 StubReplanLLM 时，本 variant
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
