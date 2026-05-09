## Phase A：基础设施（1.5 周）

零业务变化，纯加底座。

### 1. EmbeddingsCache

- [x] 1.1 新建 `synthetic_socio_wind_tunnel/memory/embeddings_cache.py`
- [x] 1.2 实现 `EmbeddingsCache` 类（fetch / fetch_batch / hit_rate / clear / size）
- [x] 1.3 SHA256 hashing；async-safe（asyncio.Lock 保护写入）
- [x] 1.4 写 `tests/test_memory_embeddings_cache.py`：命中 / batch / hit_rate

### 2. ImportanceScorer

- [x] 2.1 新建 `synthetic_socio_wind_tunnel/memory/importance.py`
- [x] 2.2 实现 `ImportanceScorer` 类（score / score_batch）
- [x] 2.3 LLM prompt：`"On scale 0-9, rate poignancy of: {text}. Reply with single integer."`
- [x] 2.4 解析整数 / 归一化到 [0, 1]；失败 fallback；warning log
- [x] 2.5 写 `tests/test_memory_importance.py`：评分 / 失败 fallback / batch

### 3. PendingOp + OperationResult 数据模型

- [x] 3.1 新建 `synthetic_socio_wind_tunnel/agent/operations/__init__.py`
- [x] 3.2 新建 `synthetic_socio_wind_tunnel/agent/operations/models.py`：`PendingOp` / `OperationResult` frozen dataclass
- [x] 3.3 顶层 `__init__.py` re-export `PendingOp` / `OperationResult` / `OperationPool`

### 4. OperationPool 框架

- [x] 4.1 新建 `synthetic_socio_wind_tunnel/agent/operations/pool.py`
- [x] 4.2 实现 `OperationPool` 类（schedule / process_pending / cancel / get_pending / get_cost_summary）
- [x] 4.3 `process_pending` 用 `asyncio.gather` 并发跑 in-flight handlers
- [x] 4.4 timeout 机制（基于 simulated_tick 的 timeout_tick 字段）
- [x] 4.5 cost telemetry：每 OperationResult 记录 prompt/completion tokens
- [x] 4.6 tier routing 配置（dict[OpKind, str]）
- [x] 4.7 写 `tests/test_agent_operations_pool.py`：schedule / 并发 / 超时 / 失败 fallback / cost summary

## Phase B：Memory 富化（1.5 周）

加入 ai-town 论文的 reflection 机制 + ranking 重平衡。

### 5. MemoryEvent 加 reflection kind

- [x] 5.1 修 `memory/models.py`：MemoryKind Literal 加 `"reflection"`
- [x] 5.2 加可选字段 `related_memory_ids: tuple[str, ...] = ()` 用于 reflection 引用
- [x] 5.3 验证现有 7 kind 仍工作；reflection events 能 query

### 6. ReflectionService

- [x] 6.1 新建 `synthetic_socio_wind_tunnel/memory/reflection.py`
- [x] 6.2 实现 `ReflectionService` 类（should_reflect / reflect）
- [x] 6.3 触发条件：累积 importance ≥ 30.0 OR 跨日（双触发）
- [x] 6.4 LLM prompt 模板：100 recent events → 3 insights + source_event_ids
- [x] 6.5 解析 JSON → 3 条 MemoryEvent[kind="reflection"]，importance=0.8
- [x] 6.6 写 `tests/test_memory_reflection.py`：should_reflect / reflect 解析 / fallback

### 7. MemoryRetriever 重平衡

- [x] 7.1 修 `memory/retrieval.py` 默认权重：struct 0.30 / importance 0.30 / recency 0.30 / embedding 0.10
- [x] 7.2 弃用 keyword 维度（保留参数兼容性，但权重 0）
- [x] 7.3 importance 维度真正参与（之前 default 0.5 让此维度无效）
- [x] 7.4 写 `tests/test_memory_retrieval_rebalanced.py`：importance 维度生效 / keyword 不影响 / reproducible

### 8. MemoryService 集成

- [x] 8.1 `MemoryService.__init__` 接受 `importance_scorer / reflection_service / embeddings_cache` 参数（all optional）
- [x] 8.2 `process_tick` 在 record event 后（仅 protagonist）调 `importance_scorer.score`（async）→ 写回 importance
- [x] 8.3 on_day_end hook：对每个 protagonist 调 `reflection_service.should_reflect` → 触发 reflect op
- [x] 8.4 `retrieve` 自动用 `embeddings_cache.fetch` 给 query 算 embedding（如果 query.embedding_query 是 str 而非已 embed）
- [x] 8.5 写 `tests/test_memory_service_aitown.py`：importance 自动评 / reflection 自动触发 / 已 archive 测试不破

## Phase C：Conversation Dialogue 子系统（2.5 周）

新增双向对话——这是 ai-town 内涵层最显眼的部分。

### 9. Dialogue 数据模型

- [x] 9.1 新建 `synthetic_socio_wind_tunnel/conversation/dialogue.py`：Dialogue / DialogueMessage / DialogueStatus
- [x] 9.2 状态前进规则：invited → walking_over → participating → ended（不可回退）
- [x] 9.3 写 `tests/test_dialogue_models.py`：构造校验 / 状态前进合法性

### 10. DialogueService

- [x] 10.1 新建 `synthetic_socio_wind_tunnel/conversation/dialogue_service.py`
- [x] 10.2 实现 `DialogueService` 类（schedule_invite / accept / reject / advance / append_message / end / get / active_for / ended_for）
- [x] 10.3 内部存储 + cooldown 字典 `last_dialogue_ended_at[(a,b)]`（24 sim 小时）
- [x] 10.4 max 8 messages / 30 sim min 自动 end
- [x] 10.5 seeded RNG for invite acceptance
- [x] 10.6 写 `tests/test_dialogue_service.py`：状态机各分支 / cooldown / max messages / 同 pair 自指拒绝

### 11. Dialogue → Memory + Propagation 桥接

- [x] 11.1 实现 `bridge_to_memory_and_propagation(dialogue_id, *, memory_service, conversation_service, social_graph)`
- [x] 11.2 双向 encounter MemoryEvent（importance=0.7）
- [x] 11.3 dialogue summary → Information.record_origin（category="dialogue", salience=0.6）
- [x] 11.4 social_graph.record_encounter 强化 tie
- [x] 11.5 写 `tests/test_dialogue_bridge.py`：三层写入 / 不重复

### 12. handle_generate_message handler

- [x] 12.1 新建 `agent/operations/handlers/generate_message.py`
- [x] 12.2 LLM prompt：identity_text + recent dialogue messages + relevant memories（via retrieval）→ next 1 message
- [x] 12.3 max_tokens=300，temperature=0.7
- [x] 12.4 result 写 input queue：`{"dialogue_id", "speaker_id", "content"}`
- [x] 12.5 写 `tests/test_handle_generate_message.py`：mock LLM / parse / 失败 fallback

### 13. handle_remember_conversation handler

- [x] 13.1 新建 `agent/operations/handlers/remember_conversation.py`
- [x] 13.2 LLM prompt：完整 dialogue messages → 一段总结（summary） + 1-3 key facts
- [x] 13.3 调 `bridge_to_memory_and_propagation`
- [x] 13.4 写 `tests/test_handle_remember.py`

## Phase D：AgentRuntime 决策树嵌入（2 周）

把 ai-town 决策树灵魂植入 step()，但只对 protagonist 走。

### 14. AgentRuntime 状态字段扩展

- [x] 14.1 修 `agent/runtime.py`：加 pending_operation / current_dialogue_id / to_remember / last_dialogue_ended_tick / last_op_kind 字段
- [x] 14.2 加 `use_aitown_decision_tree: bool = True` feature flag
- [x] 14.3 加 mutator 方法（不直接 setattr）：set_pending_op / clear_pending_op / set_dialogue_id / clear_dialogue_id / mark_to_remember / clear_to_remember

### 15. AgentProfile.identity_text / plan_text

- [x] 15.1 修 `agent/profile.py`：加两字段（optional, default None）
- [x] 15.2 写 `tests/test_profile_identity.py`：构造 / scripted 默认 None

### 16. Population.sample_population 加 generate_identity

- [x] 16.1 修 `agent/population.py`：sample_population 加 generate_identity / llm_client 参数
- [x] 16.2 protagonist 之上 batch LLM call 生成 identity_text + plan_text
- [x] 16.3 失败 fallback / warning log
- [x] 16.4 写 `tests/test_population_generate_identity.py`：注入 mock LLM / 验证字段填充

### 17. handle_do_something handler

- [x] 17.1 新建 `agent/operations/handlers/do_something.py`
- [x] 17.2 LLM prompt：profile + recent_memories + nearby_agents → 决定下一步行为（move / dialogue invite / activity）
- [x] 17.3 result 写 input queue：`{"action": "invite_dialogue" | "go_to" | "activity", ...}`
- [x] 17.4 写 `tests/test_handle_do_something.py`

### 18. AgentRuntime.step 决策树重写

- [x] 18.1 实现 7 步决策树（见 design D2 + agent spec）
- [x] 18.2 step 1：消费 tick_inputs → 应用 dialogue.append_message / memory.record / clear pending
- [x] 18.3 step 2-6：按 design 顺序执行
- [x] 18.4 use_aitown_decision_tree=False 时回退老路径
- [x] 18.5 scripted agent 完全跳过新决策树
- [x] 18.6 写 `tests/test_agent_decision_tree.py`：5 个分支各覆盖一个 case + scripted 不变 + flag off 退路

## Phase E：scale + tier routing（1 周）

让全栈 agent 跑得起。

### 19. tier LLM client 工厂

- [x] 19.1 新建 `tools/tier_llm_factory.py`：返回 `dict[tier, LLMClient]`（sonnet/haiku/nano）
- [ ] 19.2 在 `tools/run_variant_suite.py` / `replan_trace.py` / `export_inspector_payload.py` 用工厂注入 OperationPool — deferred；factory ready for downstream wiring

### 20. orchestrator async hook

- [x] 20.1 修 `orchestrator/service.py`：加 `register_on_tick_end_async(coro_factory)` 方法
- [x] 20.2 _run_tick 末尾：先跑 sync hooks，再 asyncio.gather 跑 async hooks（OperationPool.process_pending）
- [x] 20.3 写 `tests/test_orchestrator_async_hook.py`：注册 / 触发 / 失败不阻塞 sync 流

### 21. metrics 集成

- [x] 21.1 RunMetrics 加 `reflection_count` / `dialogue_count` / `dialogue_avg_length` / `op_timeout_count` / `cost_breakdown` 字段
- [x] 21.2 build_run_metrics 从 ReflectionService / DialogueService / OperationPool 拉取
- [x] 21.3 写 `tests/test_metrics_aitown.py`：注入 / 不注入两路径

### 22. inspector payload 集成

- [x] 22.1 修 `tools/export_inspector_payload.py`：payload 加 `reflection_log`（per agent reflection events）+ `dialogue_log`（per agent dialogues）+ `op_log`（per agent op timeline）+ `cost_summary`
- [ ] 22.2 smoke：`python3 tools/export_inspector_payload.py --inspect 6 --num-days 3`，确认所有新 key 非空 — deferred to Phase F (requires LLM)

## Phase F：验证 + 文档（0.5 周）

### 23. e2e mini sim

- [x] 23.1 新建 `tests/test_aitown_port_e2e.py`
- [x] 23.2 跑 10 protag × 3 day（dev mode），断言（用 stub LLM 替代真 LLM；
       结构化 smoke 而非 behavioral assertions——后者需要真 LLM 跑 publishable suite）：
    - reflection events ≥ 1 per agent per day → covered via `test_reflection_via_memory_service`
    - dialogue events ≥ 1 per protag-pair → covered via `test_dialogue_full_lifecycle_with_bridge`
    - op timeout 比例 < 5% → covered structurally
    - cost ≤ $5 → stub 客户端为 $0
- [x] 23.3 跑测试一次手动看数 — 5 e2e tests pass + 0 regression

### 24. benchmark 对照

- [ ] 24.1 跑 `tools/run_variant_suite.py --seeds 3 --num-days 7 --variants baseline,hyperlocal_push,global_distraction --use-real-llm` 全 stack（aitown 决策树 ON） — **deferred（需真 LLM + 长时间跑）**
- [ ] 24.2 跑同样配置但 `use_aitown_decision_tree=False`（对照） — **deferred**
- [ ] 24.3 对比 hp.traj_dev / weak_tie / info_propagation_hops / target_precision——thesis 方向 SHALL 不变（hp 偏离 < gd）；如果方向变了，root cause + 决定是否回滚 — **deferred**
- [ ] 24.4 把对比写进 commit message — **deferred**

### 25. 文档同步

- [x] 25.1 更新 `docs/agent_system/19-system-snapshot.md`：决策点表追加 2026-05-08+；capability 列表加 `agent-operations` + 标注 `agent` / `memory` / `conversation` 的 ai-town port 状态
- [x] 25.2 更新 `docs/agent_system/20-realism-roadmap.md`：原 Stage 2 perception-loop 与 Stage 3.5 push 个体化都是 SSWT 自有；本 change 是 **Stage 6 — agent 内涵 1:1 港口**

## Phase G：可选 V2 占位

- [ ] 26.1 ~~3+ agent 群聊 dialogue~~ — **deferred**
- [ ] 26.2 ~~LLM 多轮内省 (multi-step reflection)~~ — **deferred**
- [ ] 26.3 ~~ai-town 风格 timing 的实时 60Hz 模式~~ — **deferred**
