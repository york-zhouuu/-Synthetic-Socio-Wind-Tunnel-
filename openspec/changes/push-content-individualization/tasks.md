## 1. push_personalizer 模块 + PushTemplate

- [x] 1.1 新建 `synthetic_socio_wind_tunnel/policy_hack/personalizer.py`
- [x] 1.2 定义 frozen Pydantic `PushTemplate`（template_id / topic_id / base_content / audience_variants / target_audience_tags / base_salience）；构造校验"default" 必含 + target_audience_tags 非空 + base_salience ∈ [0,1]
- [x] 1.3 实现 `PushPersonalizer.audience_tag_for(profile)` 5 类规则
- [x] 1.4 实现 `PushPersonalizer.relevance(profile, template)` 3 档（1.0/0.6/0.3）
- [x] 1.5 实现 `PushPersonalizer.personalize(template, profile, *, location, ...)`：渲染 content + 计算 urgency + 装配 FeedItem（含 topic_id + target_audience_tags）；返回 (FeedItem, relevance)
- [x] 1.6 写 `tests/test_push_template.py`：构造校验 / frozen
- [x] 1.7 写 `tests/test_push_personalizer.py`：5 个 audience tag 命中、relevance 3 档、不同 profile 拿不同 content、relevance 影响 urgency

## 2. PushTemplate 预设池

- [x] 2.1 新建 `synthetic_socio_wind_tunnel/policy_hack/templates.py`
- [x] 2.2 定义 5 个 PushTemplate 实例：market（parents/young_adult）/ reading_group（elderly/default）/ neighbour_meet（newcomer）/ kid_event（parents）/ community_clean（default）
- [x] 2.3 export `PUSH_TEMPLATES: tuple[PushTemplate, ...]`
- [x] 2.4 顶层 `__init__.py` re-export `PushTemplate` / `PushPersonalizer` / `PUSH_TEMPLATES`
- [x] 2.5 `tests/test_push_templates_preset.py`：每条 template 通过 PushTemplate 校验、共 5-12 条、覆盖所有 5 个 audience tags

## 3. attention-channel: FeedItem 字段扩展

- [x] 3.1 `attention/models.py` 给 `FeedItem` 加 `topic_id: str | None = None` + `target_audience_tags: tuple[str, ...] = ()`
- [x] 3.2 跑现有 `tests/test_attention_models.py` + `tests/test_attention_service.py` 确认向后兼容
- [x] 3.3 加 1 个 case：构造 FeedItem 不传新字段 → 默认值正确

## 4. HyperlocalPushVariant 重构

- [x] 4.1 加 `use_personalizer: bool = True` + `personalizer: PushPersonalizer | None = None` 字段
- [x] 4.2 `apply_day_start` 分支：use_personalizer=True 时，从 PUSH_TEMPLATES rng-pick 一个 template，对每个 target agent 调 personalizer.personalize 单独 inject_feed_item（recipient list 长度=1）
- [x] 4.3 同 day 同 push 的所有 personalized FeedItem 共享 topic_id（来自 template）
- [x] 4.4 use_personalizer=False 走 legacy 路径（保留 content_templates 字段）
- [x] 4.5 写 `tests/test_hyperlocal_push_individualized.py`：parents + young_adult + elderly 三个不同 profile 收到 3 条 content 不同的 FeedItem；topic_id 一致

## 5. conversation 集成 relevance + target_audience

- [x] 5.1 `Information` 加字段 `target_audience_tags: tuple[str, ...] = ()`，frozen
- [x] 5.2 `ConversationService.__init__` 加 `relevance_provider: Callable | None = None` + `audience_tag_provider: Callable | None = None`
- [x] 5.3 share 概率公式扩展：sender × receiver relevance modifier（None 时 1.0）
- [x] 5.4 实现 `within_target_count(info_id)` / `outside_target_count(info_id)` / `target_precision_for(info_id)` / `mean_target_precision()`
- [x] 5.5 写 `tests/test_conversation_relevance.py`：未注入 provider 退化 / 注入后跨 audience 边界传播显著弱化 / target_precision 计算正确

## 6. memory 集成

- [x] 6.1 `MemoryService.process_tick` 在 origin 注入时，把 `feed_item.target_audience_tags` 透传给 `Information.target_audience_tags`
- [x] 6.2 MemoryService 持有可选 `personalizer: PushPersonalizer | None`，构造 relevance_provider + audience_tag_provider lambda 注入 conversation
- [x] 6.3 conversation 的 provider 通过 closure 拿 (info_id, agent_id) → 推 personalizer.relevance(profile, template)。需要从 (info_id) 反查 template_id —— 在 origin 注入时维护一个 `_info_to_template: dict[info_id, template_id]` mapping
- [x] 6.4 写 `tests/test_memory_personalization.py`：注入 personalizer 后 conversation 收到 relevance_provider；未注入时退化

## 7. metrics 集成

- [x] 7.1 `DayMetricsSummary` 加 `info_target_reach_today: int | None = None`
- [x] 7.2 `TickMetricsRecorder.snapshot` 在注入 conversation + audience_tag_provider 时填该字段（统计当天 first-learned 的 within-target 数）
- [x] 7.3 `RunMetrics.info_propagation_hops` dict 加 3 keys：`info_within_target_reach` / `info_outside_target_reach` / `target_precision`
- [x] 7.4 写 `tests/test_metrics_target_audience.py`：填 / 不填两路径

## 8. tools 装配

- [x] 8.1 `tools/run_variant_suite.py`：构造 PushPersonalizer + 注入 MemoryService（让 conversation 拿到 provider）
- [x] 8.2 `tools/replan_trace.py` 同步注入
- [x] 8.3 `tools/export_inspector_payload.py`：payload 加 personalization metadata（每 inspected agent 的 audience_tag）+ per-info target_precision
- [x] 8.4 smoke：`python3 tools/export_inspector_payload.py --inspect 4 --num-days 3`

## 9. e2e mini sim 验证

- [x] 9.1 写 `tests/test_personalization_integration.py`：50 agent × 3 day × baseline + hp + gd（stub LLM），断言：
    - hp 的 push content 各 agent 不同（验证 individualized）
    - hp 的 target_precision > 0.5
    - gd 不应受 personalization 影响（仍 broadcast）
    - hp 的 info_within_target_reach > info_outside_target_reach
- [x] 9.2 跑测试一次手动看数

## 10. dev publishable suite 验证 — DEFERRED

- [x] 10.1 ~~跑 5 seed × 7 day real LLM 验证 hp.target_precision vs gd~~ — **deferred** 到下次 publishable suite
- [x] 10.2 ~~比较与上次 v3 publishable 数据~~ — **deferred**

**为什么 defer**：本 change 已通过 e2e mini sim 验证 personalization 在 hp / gd 下行为正确（hp.target_precision > 0；gd 正确显示 0）。"hp.target_precision 在真 LLM publishable 下达到 ≥ 0.7" 这是 publishable scale 实证问题，与 conversation-capability 一并验证。

## 11. 文档同步

- [x] 11.1 更新 `docs/agent_system/19-system-snapshot.md`：决策点表追加；Gap 不变（push-content-individualization 是子模块，不是新 capability）
- [x] 11.2 更新 `docs/agent_system/20-realism-roadmap.md`：标记 Stage 3.5（push 内容个体化）已完成

## 12. 可选：V2 占位

- [x] 12.1 ~~LLM 生成内容~~ — **deferred to V2**
- [x] 12.2 ~~个体化 timing~~ — **deferred to V2**
- [x] 12.3 ~~多语言 LLM 翻译~~ — **deferred to V2**
