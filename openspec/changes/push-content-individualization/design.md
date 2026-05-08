## Context

`HyperlocalPushVariant.apply_day_start` 当前生成**单条 FeedItem 广播给所有 target_ids**：

```python
template = ctx.rng.choice(self.content_templates)
content = template.format(location=self.target_location)
item = FeedItem(content=content, ...)
ctx.attention_service.inject_feed_item(item, target_ids)
```

每个 target agent 收到完全相同的字符串。conversation 层把这条 FeedItem 转成一个 Information，所有 target agents 立刻 known，hops=0。

问题（proposal Why 详述）：
1. mirror（global_distraction）做同样事情：broadcast generic content。两者只在 base salience 差。**没有 content 个体化的对照** → mirror 与 hp 对照不彻底。
2. conversation 的 share 概率公式不看"内容相关性"——只看 tie strength + extraversion。没有 sender/receiver 的内容相关度，hp viral 起不来。

本 change 让 hp 真正"hyperlocal"：每个 agent 收到针对 ta profile 个体化的 FeedItem，用同一 `topic_id` 在 conversation 层聚合成一条 Information，但 sender / receiver 各自的 relevance 调整 share 概率。

## Goals / Non-Goals

**Goals**

1. **per-agent 个体化 content**：market push 给 mary（70 岁退休）和 emma（25 岁单身）的字符串**不一样**——audience-aware 内容
2. **same topic, different views**：所有 personalized FeedItem 共享 topic_id；conversation 聚合成同一 Information；不破坏 propagation 模型
3. **relevance 调 share**：sender / receiver 与 topic 的匹配度调整 share 概率——不感兴趣的人不愿提一嘴 / 不愿听
4. **target_precision metric**：hp 应显著高于 gd（hp 内容个体化 → 触达 target 人群比例高；gd 不个体化 → 低）
5. **零侵入旧 path**：personalizer 是 optional；不传 → variant_a 退回原 generic content；conversation 的 relevance modifier 缺省 = 1.0

**Non-Goals**

- ❌ LLM 生成内容（V2）
- ❌ Personalized timing
- ❌ Multi-language LLM 翻译
- ❌ A/B testing framework
- ❌ Per-agent push frequency（仍每日一次）
- ❌ Sender 主动选择"该跟谁说"（V2；现在仍是 encounter-driven）

## Decisions

### D1：FeedItem 加 `topic_id`，conversation 用它聚合

**做什么**：`FeedItem` 加 `topic_id: str | None = None`。当 personalizer 渲染 N 个 personalized FeedItem 时，它们共享同一 topic_id（如 `"hp_market_42_0"`）。

`MemoryService.process_tick` 注入 conversation origin 时，**用 topic_id 作为 info_id 的 key**（如果 topic_id 存在；否则降级到 feed_item_id）：
```python
info_id = f"info_{feed_item.topic_id or feed_item.feed_item_id}"
```

效果：emma 收到 `feed_item_emma`（content_emma），mary 收到 `feed_item_mary`（content_mary）；两人都被 `record_origin` 加进同一个 `info_hp_market_42_0` 的 known set，hops=0。

**理由**：保留 conversation 的 propagation 模型（一个 Information 跨多 agent），同时让 each agent 拥有不同 content view。emma 跟 mary 第二天 encounter 时，能 share 同一 topic（concept-level 共享，不要求字符串一致）。

**Alternatives considered**：

- **A. 每个 personalized FeedItem → 一条独立 Information**：拒绝。同一 push event 变成 N 个 info，propagation 完全切断。
- **B. 用 origin_hack_id 作为 topic key**：拒绝。`origin_hack_id="hyperlocal_push"` 太粗，跨日 + 跨 push event 全混到一个 info。
- **C. 选 D1（topic_id 显式字段）** —— ✓ 语义清晰；向后兼容（None 时退到 feed_item_id）。

### D2：PushTemplate.audience_variants 是字符串字典，不是函数

**做什么**：
```python
class PushTemplate(BaseModel):
    template_id: str
    topic_id: str
    base_content: str
    audience_variants: dict[str, str]    # audience_tag → 字符串
    target_audience_tags: tuple[str, ...]
    base_salience: float
```

PushPersonalizer 给 profile 算一个 audience_tag（"parents" / "young_adult" / "elderly" / "newcomer" / "default"），从 `audience_variants` 取 string。

**理由**：
- 字符串可序列化、可在 git 里 review、可让产品 / 内容人员直接编辑
- 不是 function 因为不需要执行复杂逻辑——profile → tag 是 simple rule，tag → content 是固定 lookup
- 测试容易（不需要 mock function）

**Alternatives considered**：
- **A. content 是 callable `(profile) -> str`** —— 拒绝。难以序列化 / 难 review / 难测试。
- **B. content 是 jinja2 template** —— 拒绝。增加依赖且不需要逻辑分支。
- **C. 选 D2（字典 lookup）** —— ✓ 简单。

### D3：profile → audience_tag 的 5 类规则

```python
def _audience_tag_for(profile: AgentProfile) -> str:
    if profile.family_composition == "couple_kids_under_15":
        return "parents"
    if profile.community_tenure == "new_<1yr":
        return "newcomer"
    if profile.age >= 65 or profile.community_tenure == "established_5plus":
        return "elderly"
    if profile.age < 30 and profile.household == "single":
        return "young_adult"
    return "default"
```

5 个 tag 覆盖大多数 profile（互斥）。每个 PushTemplate 必须包含 "default" 变体作为 fallback。

**理由**：rule-based 简单确定。未来想加 "language_chinese" 之类，往函数里加 if 即可。复杂个体化（多维 weighted scoring）不在 V1。

### D4：relevance score 是 audience_tag 与 target_audience_tags 的成员关系判定

```python
def relevance(profile: AgentProfile, template: PushTemplate) -> float:
    tag = _audience_tag_for(profile)
    if tag in template.target_audience_tags:
        return 1.0   # 完全 target 群体
    if tag == "default":
        return 0.6   # 普通人，中等相关
    return 0.3       # 跟 target 不重合（e.g. 给 newcomer 推老居民活动）
```

**理由**：3 档简单。未来可加权（profile × topic × time），但 V1 不做。

`urgency` 在 hyperlocal_push.apply_day_start 里：
```python
urgency = base_urgency × (0.5 + 0.5 × relevance)
# relevance=1.0 → urgency × 1.0 (不变)
# relevance=0.6 → urgency × 0.8
# relevance=0.3 → urgency × 0.65
```

### D5：conversation 的 relevance_provider 是 `Callable[[info_id, agent_id], float]`

**做什么**：ConversationService 加 `relevance_provider: Callable | None = None` 构造参数。
process_tick 计算 share 概率时：
```python
sender_relevance = relevance_provider(info_id, sender) if provider else 1.0
receiver_relevance = relevance_provider(info_id, receiver) if provider else 1.0
P = base × tie_mod × pers_mod × salience × recency_decay × sender_relevance × receiver_relevance
```

由 `MemoryService` 在 origin 注入时构造 provider：基于 `(info_id, agent_id) -> personalizer.relevance(profile, template)` 的查表。

**Alternatives considered**：

- **A. Information 自带 `relevance_for: dict[agent_id, float]` 字段** —— 拒绝。Information 是 frozen 数据；relevance 是 derived，应该在 service 层。
- **B. 在 conversation.process_tick 直接接受 personalizer 引用** —— 拒绝。conversation 不应该懂 PushTemplate 概念；通过 callable 解耦。
- **C. 选 D5（Callable）** —— ✓ 解耦清晰，conversation 不依赖 policy_hack。

### D6：`target_precision` metric 的定义

```python
target_precision = info_within_target_reach / max(1, total_reach)
```

每条 info 的 `target_audience_tags` 是 push 设计时声明的"该听到的人"。`within_target_reach` = 触达 agents 中 audience_tag ∈ target_audience_tags 的数。

汇总到 RunMetrics 时：
```python
info_propagation_hops["target_precision"] = mean(per_info_target_precision)
```

预期：hp 因为内容个体化、relevance 高的 agent 更愿 share / 接 share，**target_precision ≥ 0.7**。gd 因为不个体化，target_audience_tags = ()（空），**target_precision = 0**（mirror 设计中 gd 没有"目标受众"）。这是清晰的对照。

## Risks / Trade-offs

[**风险 R1**] 5 个 audience_tag 太粗——很多 profile 落到 "default"，个体化效果不显著
→ **Mitigation**：先用 5 个 tag 跑 e2e。如果 default 占比 > 60%，加细 tag（e.g. "young_adult_with_pet" / "established_renter"）。Lane Cove ABS 数据足以支持更细分。

[**风险 R2**] target_audience_tags = () 的 template（如 generic）让 relevance 总是 0.6（default tag），变相鼓励所有人 share
→ **Mitigation**：明确约定 PushTemplate 必须声明非空 target_audience_tags（spec 强制）。GlobalDistractionVariant 故意不用 PushPersonalizer——保留原 broadcast generic 路径作为 mirror。

[**风险 R3**] D1 用 topic_id 作 info_id key，但旧 caller（test 等）传 None topic_id，info_id 仍走 feed_item_id 路径——同一 push 的多个 personalized item 各自一个 Information，propagation 切断
→ **Mitigation**：HyperlocalPushVariant 在使用 personalizer 时**强制写 topic_id**；`_salience_from_feed` 里加 assertion / fallback。spec 在变更要求里写明：personalizer 路径必生成 topic_id。

[**风险 R4**] sender/receiver relevance 都低（都是 0.3）时，公式连乘 → P 很小（× 0.09 = 大约不可能 share）。会不会导致 hp 内"目标人群外"的信息完全死循环、跑出 unreal 的极端分布？
→ **Mitigation**：这正是设计目标——非目标人群不应该传播。但若数据显示 hp 的 0-1 hop reach 够好但 2+ hops 反而比 baseline 还低，说明 relevance 公式过严。届时把 0.3 调到 0.5 或改 sqrt(sender × receiver)。

[**风险 R5**] V1 的 PushTemplate 池只有 5-8 个，跑 14 天每天 1 push 共 14 push，重复严重——agent 短时间内被同 topic 推 N 次
→ **Mitigation**：HyperlocalPushVariant 的 daily 选择从 templates 中带 weighting；同一 topic_id 当周不重复（rng-based dedup）。Acceptable for V1：14 天能跑出多个 unique topics，足够。

## Migration Plan

无破坏性 API 变更。

1. **Step 1**：实现 push_personalizer 模块（PushTemplate + 5 个 templates + Personalizer）+ 单元测试
2. **Step 2**：FeedItem 加 topic_id / target_audience_tags（向后兼容 None default）
3. **Step 3**：HyperlocalPushVariant 重构用 personalizer；保留旧 `content_templates` 字段做 fallback
4. **Step 4**：conversation 接 relevance_provider；公式扩展
5. **Step 5**：MemoryService 在 origin 注入时构造 provider 并传给 conversation
6. **Step 6**：metrics 加 target_precision keys
7. **Step 7**：tools 装配（不需要改，hyperlocal_push 内部已切换）
8. **Step 8**：跑 e2e mini sim 验证 hp.target_precision 高、gd 没受影响
9. **Step 9**：commit + archive；下个 publishable run 跑全 push-content 个体化

回滚：HyperlocalPushVariant 加 `use_personalizer: bool = True`；False 时退回原 broadcast 路径。

## Open Questions

1. **Q1**：5 个 audience tags 够吗？还是该 7-8 个？
   - **倾向**：先 5 个跑 e2e。看 default 占比决定。

2. **Q2**：relevance 用 hard categorical (1.0/0.6/0.3) 还是 soft scoring？
   - **倾向**：V1 hard。soft 留 V2，需要更多 calibration data。

3. **Q3**：PushTemplate 池是 hand-crafted in-code 还是 YAML？
   - **倾向**：hand-crafted python 文件。可 review、IDE 支持、Pydantic 校验。当数量 > 30 时再考虑 YAML 抽离。

4. **Q4**：global_distraction 是否也应该用 personalizer，但配置成 "no target"（所有人都是 default tag）？
   - **倾向**：不。mirror 的核心设计就是"不个体化"。让它走原 broadcast 路径，更鲜明。

5. **Q5**：conversation 的 relevance modifier 之间是 `relevance_a × relevance_b`（连乘）还是 `(relevance_a + relevance_b) / 2`（均值）？
   - **倾向**：连乘。两侧都不感兴趣应该接近 0；连乘语义对。
