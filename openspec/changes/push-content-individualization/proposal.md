## Why

attention-rebalance + social-graph + conversation 三个 change 让 sim 在结构上能跑出 thesis 全链条——但 push **内容**仍然是模板字符串：

```
"本街正在举办市集"   # 同一字符串发给 emma（25 岁单身）和 mary（70 岁退休）
```

这是 hp variant 的最后一个 prompt artifact 嫌疑：

1. **真实 hyperlocal 应用不这么推**：Lane Cove Council Facebook / Lane Cove Living / Inner West Mums——每个渠道的内容都是受众分层的（"为孩子家长" / "为新搬来住户" / "中文社区"）。我们的 sim 把所有 hp push 写成同一句话，这个层面上跟 mirror（global_distraction）的 push 没有质的不同——都是"对所有人推同一内容"，只是 mirror 的 salience 低些而已。
2. **conversation 层的 salience 现在是 info 级别 const**：emma 和 mary 看到同一条 "本街市集"，conversation 给两人**完全相同的 share 概率**。但现实中 emma 可能对市集有兴趣（年轻 + 高 curiosity），mary 不一定（退休 + 高 routine_adherence）。**relevance 这层缺失**让 hp 与 mirror 的对照不彻底。
3. **thesis 论证的真正爆点在第二跳**：emma 收到内容后转给 mary 的概率应该取决于"emma 觉得 mary 会感兴趣吗"——也就是 **sender 觉得 receiver 是否相关**。当前 conversation 只看 tie strength + extraversion，**不看内容相关性**。这正是 hp viral 不起来的核心机制缺口。

修这层的 ROI：

- 让 hp variant 的 effect 从"普遍偏离"变成"目标人群偏离" —— mary 不会被推动而 emma 会。这跟现实匹配。
- 让 conversation 的 hp vs gd 对照彻底化：不只是 base salience 0.8 vs 0.3 的差，是**整张人群 × 内容的 relevance 矩阵**的差。
- 给即将跑的 publishable suite 一个新 thesis-direct metric：`info_propagation_within_target_audience`（push 是否真传到了"本来该听到的人"那里）。

## What Changes

### 新模块：`push_personalizer`（policy-hack 子模块）

新建 `synthetic_socio_wind_tunnel/policy_hack/personalizer.py`：

- **`PushTemplate` 数据模型**（frozen Pydantic）：参数化推送内容
  - `template_id`: str
  - `topic_id`: str（"hyperlocal_market" / "library_reading_group" / 等；同一 topic 的所有 personalized 实例共享 conversation 层 Information）
  - `base_content`: str（含 `{location}` / `{audience}` 等 placeholder）
  - `audience_variants: dict[str, str]`（按受众细分的 content 变体，e.g. `{"parents": "...孩子家长可来...", "young_adult": "...第一次办，欢迎新邻居...", "elderly": "...无障碍通道..."}`）
  - `target_audience_tags: tuple[str, ...]`（这条 push 真正要触达的 audience 类型）
  - `base_salience: float`（topic 级别基础显著度）

- **`PushPersonalizer` 服务**：profile → 个体化 FeedItem
  - `personalize(template, profile, *, location, ...) -> FeedItem`
  - 内部根据 profile 的 family_composition / age / community_tenure / language_at_home 选择 audience 变体填 content
  - 同时返回 `relevance: float ∈ [0, 1]`：profile 跟 target_audience_tags 的匹配度
  - 不匹配时 relevance 低（仍然个体化 content，但 salience 衰减）；匹配时 relevance 高
  - 算法：基于 profile 19 维 vs target_audience_tags 的 rule-based 评分

### Modified：`attention-channel`

`FeedItem` 加两个字段（向后兼容，default None）：
- `topic_id: str | None = None`：同一 topic 的所有 personalized 实例共享此 ID（conversation 层用它聚合）
- `target_audience_tags: tuple[str, ...] = ()`：metadata，metric 层用来检查"是否传到 target 人群"

### Modified：`policy-hack`

`HyperlocalPushVariant.apply_day_start` 重构：
- 旧：渲染一条 content，broadcast 给所有 target_ids
- 新：用 `PushPersonalizer` 给每个 target_id **生成一条个体化 FeedItem**，内容根据 profile 不同
- 所有这些 FeedItem 共享同一个 `topic_id`（让 conversation 聚合成一条 Information）
- 每条 FeedItem 的 urgency 用 personalizer 算的 relevance 调整：`urgency = base_urgency × (0.5 + 0.5 × relevance)`

`GlobalDistractionVariant`（mirror）**保持** broadcast generic content（不个体化）—— 这是 mirror 设计的核心：正向干预个体化 / 反向干预泛化。两者的 metric 差距让 thesis 立得住。

### Modified：`conversation`

- `Information` 加可选字段 `target_audience_tags: tuple[str, ...] = ()`（从 FeedItem.target_audience_tags 透传）
- `ConversationService.record_origin` 接受 origin 时的 agent profile 推 `_relevance` 表 `dict[(info_id, agent_id), float]`
- `ConversationService.process_tick` 中 share 概率公式扩展：
  ```
  P = base × tie_mod × pers_mod × salience × recency_decay × sender_relevance × receiver_relevance
  ```
  - `sender_relevance` 来自 sender 与该 info topic 的匹配度（如果不匹配，sender 不那么愿意"提一嘴"）
  - `receiver_relevance` 来自 receiver 与该 info topic 的匹配度（不感兴趣的人不会接 share）
  - 未注入 personalizer 时两个 modifier 都 = 1.0（向后兼容）
- 新增 metric：`info_reaching_within_target_audience`（每条 info 触达的 agent 中，profile 落在 `target_audience_tags` 内的比例）

### Modified：`metrics`

`RunMetrics.info_propagation_hops` 新增字段（V2 不破坏，向 dict 加 keys）：
- `info_within_target_reach: int`（触达目标受众内的 agent 总数）
- `info_outside_target_reach: int`（"漏出"到非目标的 agent 数）
- `target_precision: float`（in-target / total-reach；越接近 1 = 个体化做对了）

`DayMetricsSummary` 加 1 字段：
- `info_target_reach_today: int`

### 非目标（Non-goals）

- ❌ **LLM 生成 push 内容**（V2）。本 V1 用 hand-crafted PushTemplate 池，~5-8 个 topic_id × ~3 个 audience 变体 = 15-24 个固定字符串
- ❌ **个体化 timing**：依然每天上午 9 点统一推；timing 个性化留 V2
- ❌ **多语言 LLM 翻译**：language_at_home != "english" 的 agent 拿"中文版" template，但内容是预先准备好的中文字符串，不调 LLM 翻译
- ❌ **A/B testing 框架**：所有 hyperlocal_push 走同一个 personalizer
- ❌ **历史回填**：personalizer 不查历史，只看当前 profile

## Capabilities

### New Capabilities

无新顶层 capability。`push_personalizer` 是 `policy-hack` 子模块（不是独立 capability）。

### Modified Capabilities

- `policy-hack`：`HyperlocalPushVariant` 用 `PushPersonalizer`；新建 `PushTemplate` 模型；新建 `Personalizer` 主入口
- `attention-channel`：`FeedItem` 加 `topic_id` + `target_audience_tags`（向后兼容）
- `conversation`：`Information` 加 `target_audience_tags`；`ConversationService.process_tick` 接受 `relevance_provider` 可选回调；share 概率公式加 sender + receiver relevance modifier；新增 `info_reaching_within_target_audience` 查询
- `metrics`：`RunMetrics.info_propagation_hops` dict 加 3 个 key；`DayMetricsSummary` 加 1 字段

### Untouched

- `agent` / `social-graph` / `atlas` / `ledger` / `engine` / `perception`：不动
- `orchestrator` / `multi-day-run` / `memory`：不动（除了 conversation 的 origin 注入要把 profile 也传给 personalizer，这点已在 conversation spec 内）

## Impact

**代码新增**：
- `synthetic_socio_wind_tunnel/policy_hack/personalizer.py`（PushTemplate + PushPersonalizer）
- `synthetic_socio_wind_tunnel/policy_hack/templates.py`（5-8 个预设 PushTemplate 实例：market / reading_group / yard_sale / kid_event / new_neighbor_meet / etc.）

**代码修改**：
- `synthetic_socio_wind_tunnel/attention/models.py`（FeedItem 加 2 字段）
- `synthetic_socio_wind_tunnel/policy_hack/variants/hyperlocal_push.py`（用 personalizer 替换模板字符串）
- `synthetic_socio_wind_tunnel/conversation/models.py`（Information 加 target_audience_tags）
- `synthetic_socio_wind_tunnel/conversation/service.py`（接受 relevance_provider；公式扩展）
- `synthetic_socio_wind_tunnel/memory/service.py`（origin 注入时把 personalizer 引用传给 conversation）
- `synthetic_socio_wind_tunnel/metrics/factory.py`（填新 keys）
- `synthetic_socio_wind_tunnel/metrics/models.py`（DayMetricsSummary 加字段）
- 顶层 `__init__.py` re-export

**测试新增**：
- `tests/test_push_template.py`（PushTemplate frozen / audience_variants 完整性）
- `tests/test_push_personalizer.py`（profile match logic / relevance scoring / 不同 profile 同 template 出不同 content）
- `tests/test_hyperlocal_push_individualized.py`（variant_a 重构后每 agent 收到不同 FeedItem）
- `tests/test_conversation_relevance.py`（公式扩展 + 不注入 provider 时退化）
- `tests/test_metrics_target_audience.py`（target_precision / within_target_reach）

**Suite 影响**：
- 跑下次 publishable suite 自动产出 `target_precision` 指标
- 预期 hp 的 `target_precision` 显著高于 gd 的（gd 不个体化 → precision 低 / 信息漏到非目标人群）
- 信息 viral 模式可观察：高 relevance pair 之间传播快，跨 audience 边界传播慢

**Non-goals reaffirmed**：
- ❌ V1 不调 LLM 生成内容
- ❌ V1 不做时间个性化
- ❌ V1 不重写 mirror（global_distraction 故意 NOT 个体化，作为对照）
