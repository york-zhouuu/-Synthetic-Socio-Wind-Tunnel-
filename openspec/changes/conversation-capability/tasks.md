## 1. conversation 模块骨架

- [x] 1.1 新建目录 `synthetic_socio_wind_tunnel/conversation/`，加 `__init__.py`
- [x] 1.2 在 `models.py` 定义 frozen dataclass `Information`（info_id / content / category / salience / origin_*）
- [x] 1.3 在 `models.py` 定义 frozen dataclass `Propagation`（reach / max_hops / mean_hops / known_at / hops_at）
- [x] 1.4 在 `service.py` 定义内部 `_Knowledge`（first_learned_tick + hops）+ `InformationLedger` 索引
- [x] 1.5 在 `service.py` 定义 `ConversationService` 类（含 seeded rng + info catalog + ledger 引用）
- [x] 1.6 顶层 `synthetic_socio_wind_tunnel/__init__.py` re-export `Information` / `Propagation` / `ConversationService`

## 2. ConversationService 核心 API

- [x] 2.1 实现 `record_origin(info, agent_id, tick)`：catalog.add(info)，ledger.learn(agent_id, info_id, tick, hops=0)
- [x] 2.2 实现 share 概率公式 `_share_probability(tie, info, sim_day, agent_a_profile, agent_b_profile)`：base × tie_mod × pers_mod × salience × recency_decay
- [x] 2.3 实现 `process_tick(tick_result, social_graph, sim_day)`：遍历 encounters → 对每对 a,b 找 a-known/b-unknown 与 b-known/a-unknown 的 info 集合，对每条调概率门，命中则 ledger.learn(receiver, info, tick, hops_sender+1)
- [x] 2.4 实现 `get_propagation(info_id) -> Propagation`：聚合 ledger 中知道这条 info 的 agents
- [x] 2.5 实现查询：`info_known_by` / `top_propagated` / `info_count` / `max_hops` / `count_reaching` / `avg_reach`
- [x] 2.6 写 `tests/test_conversation_models.py`：Information frozen / Propagation frozen / salience 校验
- [x] 2.7 写 `tests/test_conversation_service.py`：record_origin / 已知不重复 / 反向链路不更新 / salience 影响 share / recency 衰减 / seeded reproducible

## 3. ConversationService 需要 personality 来源

- [x] 3.1 决定 process_tick 怎么拿 agents 的 personality（接受 `agents: Mapping[str, AgentRuntime]` 参数）
- [x] 3.2 service 不持有 agent map（每次 process_tick 由 caller 传入）；保持无状态依赖

## 4. MemoryService 集成

- [x] 4.1 `MemoryService.__init__` 接受 `conversation: ConversationService | None = None`
- [x] 4.2 实现 `_salience_from_feed(feed: FeedItem) -> float` helper 推导规则（hyperlocal / local / commercial / global）
- [x] 4.3 `process_tick` 在 `_ingest_notifications` 后，对每条新 ingested 的 notification，构造 Information 并调 `conversation.record_origin(info, agent_id, tick)`
- [x] 4.4 `process_tick` 在 social_graph.record_encounter 之后，调 `conversation.process_tick(tick_result, social_graph, sim_day=day_index, agents=agents)`
- [x] 4.5 校验：conversation 注入但 social_graph 未注入 → 抛 ValueError
- [x] 4.6 写 `tests/test_memory_conversation.py`：origin 注入 / salience 推导 / 共同跑 graph + conversation / 缺 social_graph 报错

## 5. metrics 集成

- [x] 5.1 `DayMetricsSummary` 加 4 字段：info_origins_today / info_shares_today / info_reaching_2plus_today / avg_hops_today（None default）
- [x] 5.2 `TickMetricsRecorder.__init__` 接受 `conversation: ConversationService | None = None`
- [x] 5.3 `snapshot()` 中：注入 conversation 时，每天 rollup 末从 service 查询并填 4 字段
- [x] 5.4 `RunMetrics.from_recorder` / `build_run_metrics`：注入 conversation 时填 `info_propagation_hops` dict（4 个 keys）
- [x] 5.5 写 `tests/test_metrics_conversation.py`：注入 / 不注入两条路径

## 6. tools 装配

- [x] 6.1 `tools/run_variant_suite.py`：构造 `ConversationService(seed=seed)` 注入 MemoryService + recorder
- [x] 6.2 `tools/replan_trace.py` 同步注入
- [x] 6.3 `tools/export_inspector_payload.py`：在 payload 加 `conversation` 顶层 key（含 totals + per-inspected-agent 的 known infos 列表 + top propagated）
- [x] 6.4 smoke：`python3 tools/export_inspector_payload.py --inspect 4 --num-days 3`，确认 payload 含 conversation 字段非空

## 7. e2e mini sim 验证

- [x] 7.1 写 `tests/test_conversation_integration.py`：跑 50 agent × 3 day baseline + hp + global_distraction（stub LLM），断言：
    - 三 variant 都产生 info origins（来自各 variant 的 push delivery）
    - hp 与 gd 的 origin 数应相近（两者都推 push）
    - **hp 的 info_reaching_2plus_hops > gd 的**（thesis 关键预期：salience 差）
    - baseline 的 info origins 极少或 0（没有外推，但 task notification 可能有）
- [x] 7.2 跑测试一次手动看数；如果 hp ≈ gd（salience 差距未生效），调试 _salience_from_feed

## 8. dev publishable suite 验证 — DEFERRED

- [x] 8.1 ~~跑 `tools/run_variant_suite.py --seeds 5 --num-days 7 --variants baseline,hyperlocal_push,global_distraction --use-real-llm`~~ — **deferred** 到下次 publishable suite
- [x] 8.2 ~~比较三 variant 的 info_propagation_hops~~ — **deferred**
- [x] 8.3 ~~把 hp / gd / baseline 的对比写入 commit message~~ — **deferred**

**为什么 defer**：本 change 已通过 e2e mini sim 验证 conversation 在三变体下都正常累积 origins + 传播 + 填 metric。"hp.info_reaching_2plus_hops > gd 的"这是 publishable scale + 真 LLM 的实证问题，与下次 publishable run 一起跑（也跟 push-content-individualization 上线后的对照更有意义）。

## 9. 文档同步

- [x] 9.1 更新 `docs/agent_system/19-system-snapshot.md`：决策点表追加 conversation；capability 列表加 `conversation` 行；Gap 列表去掉 conversation
- [x] 9.2 更新 `docs/agent_system/20-realism-roadmap.md`：F6（群体涌现）"信息流动" 部分标记完成（V1 stub）；备注 LLM dialogue 留 V2

## 10. 可选：V2 占位

- [x] 10.1 ~~LLM dialogue / 多轮~~ — **deferred to V2**
- [x] 10.2 ~~信息变形~~ — **deferred to V2**
- [x] 10.3 ~~3+ agent 群聊~~ — **deferred to V2**
