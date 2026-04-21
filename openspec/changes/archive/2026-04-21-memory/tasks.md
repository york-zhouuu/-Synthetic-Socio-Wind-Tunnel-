## 1. 数据模型

- [x] 1.1 创建 `synthetic_socio_wind_tunnel/memory/` 目录 + `__init__.py`
- [x] 1.2 `memory/models.py`：定义 `MemoryEvent`（frozen dataclass，7 个 kind 字面量 + 索引字段）
- [x] 1.3 `memory/models.py`：定义 `MemoryQuery`（frozen）、`DailySummary`（frozen）
- [x] 1.4 `memory/embedding.py`：`EmbeddingProvider` Protocol + `NullEmbedding`（hash-based 32 维）
- [x] 1.5 写 `tests/test_memory_models.py`：frozen / 可哈希 / NullEmbedding 确定性

## 2. MemoryStore

- [x] 2.1 `memory/store.py`：`MemoryStore` per-agent 容器
- [x] 2.2 append O(1) + 4 路倒排索引更新
- [x] 2.3 查询方法：`recent(n)` / `by_actor` / `by_location` / `by_tag` / `by_kind`
- [x] 2.4 写 `tests/test_memory_store.py`：append 顺序 / 4 路索引正确性 / 重启即清

## 3. MemoryRetriever

- [x] 3.1 `memory/retrieval.py`：`MemoryRetriever` 类（接 weights + half_life）
- [x] 3.2 实现 4 子分：structural / keyword / recency / embedding
- [x] 3.3 候选池策略：4 路索引并集，全空时回退最近 200
- [x] 3.4 min_importance 预过滤
- [x] 3.5 top_k 排序：得分降序，同分时 tick 降序
- [x] 3.6 写 `tests/test_memory_retrieval.py`：各子分独立测 + 混合打分 + null embedding 退化

## 4. MemoryService

- [x] 4.1 `memory/service.py`：`MemoryService` 类，per-agent MemoryStore 字典
- [x] 4.2 `record(agent_id, event)`：写入 + 若有 provider 则生成 embedding
- [x] 4.3 `retrieve(agent_id, query, top_k)`：门面方法
- [x] 4.4 `recent(agent_id, last_ticks)` / `all_for(agent_id)`
- [x] 4.5 写 `tests/test_memory_service.py`：agent 隔离 / embedding 生成 / 写入检索

## 5. Orchestrator 集成 (process_tick)

- [x] 5.1 `MemoryService.process_tick(tick_result, agents, planner)`：从 TickResult 派生 action / encounter events
- [x] 5.2 从 AttentionService 查询本 tick 新 notifications，派生 notification / task_received events
- [x] 5.3 遍历 agents 调 should_replan；True 即调 planner.replan 替换 plan；一 tick 一 agent 最多一次（break）
- [x] 5.4 `MemoryService.attach_to(orchestrator)`：注册 `process_tick` 到 on_tick_end hook
- [x] 5.5 写 `tests/test_memory_orchestrator_integration.py`：action / encounter 双向 / notification / replan 触发一次

## 6. AgentRuntime.should_replan

- [x] 6.1 `agent/runtime.py` 追加 `should_replan(memory_view, candidate) -> bool`
- [x] 6.2 默认规则按 kind 分支（notification / encounter / task_received）；基于 routine_adherence + curiosity 计算
- [x] 6.3 **纯代码**，不引用 LLMClient / anthropic / 网络
- [x] 6.4 写 `tests/test_agent_should_replan.py`：每个 kind 分支 + 边界 trait 值

## 7. Planner.replan

- [x] 7.1 `agent/planner.py` 追加 `async replan(profile, current_plan, interrupt_ctx) -> DailyPlan`
- [x] 7.2 构造 replan prompt（模板复用 Phase 1 的 _PLAN_PROMPT_TEMPLATE 风格 + interrupt_ctx）
- [x] 7.3 调用 `llm_client.generate(prompt, model=profile.base_model)` 1 次
- [x] 7.4 解析 JSON，保留原 steps[:current_step_index]，替换后续
- [x] 7.5 LLM 失败 fallback：返回原 plan 副本，日志标 "replan_failed"，不抛
- [x] 7.6 写 `tests/test_planner_replan.py`：MockLLM 成功 / 失败 fallback / prompt 含 interrupt context

## 8. DailySummary

- [x] 8.1 `MemoryService.run_daily_summary(agents, llm_client)` 异步
- [x] 8.2 每 agent 1 次 LLM 调用，prompt 含当日 MemoryEvent
- [x] 8.3 回填 tags + importance 到原 event（不可变替换）
- [x] 8.4 写一条 kind="daily_summary" 的 MemoryEvent 作为索引入口
- [x] 8.5 LLM 失败 fallback：summary_text="(unavailable)"，不抛
- [x] 8.6 写 `tests/test_memory_daily_summary.py`：N agents → N LLM 调用 / 失败不影响其它

## 9. 公共 API & 回归

- [x] 9.1 `synthetic_socio_wind_tunnel/__init__.py` re-export `MemoryService` / `MemoryEvent` / `MemoryQuery` / `EmbeddingProvider` / `NullEmbedding`
- [x] 9.2 `python3 -c "from synthetic_socio_wind_tunnel import MemoryService; print('OK')"` 确认
- [x] 9.3 跑全量 `python -m pytest tests/ -v`，Phase 1 / 1.5 / orchestrator 所有测试仍 PASS
- [x] 9.4 跑 `make fitness-audit`：确认 `phase2-gaps.memory` 由 FAIL 转 PASS
- [x] 9.5 检查 `e3.shared-task-memory-seam` 条目：若加了 task_received kind 应可翻绿；否则保留 SKIP 并记录 mitigation=policy-hack

## 10. Archive 前

- [x] 10.1 `openspec validate memory` 无错误
- [x] 10.2 在 Lane Cove atlas 上写一个 smoke demo：5 agent × 288 tick，至少 1 次 replan 触发，memory 能被 retrieve 出来
- [x] 10.3 文档：`docs/agent_system/09-memory-and-replan.md`（一页）：4-way 检索 + should_replan 规则 + replan 流程
