## ADDED Requirements

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

## MODIFIED Requirements

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
