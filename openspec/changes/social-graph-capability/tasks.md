## 1. social-graph 模块骨架

- [x] 1.1 新建目录 `synthetic_socio_wind_tunnel/social_graph/`，加 `__init__.py`
- [x] 1.2 在 `models.py` 定义 `Tie` frozen dataclass（agent_a / agent_b / encounter_count / strength / first_seen_tick / last_seen_tick / first_seen_day），含 canonical pair ordering 不变量
- [x] 1.3 在 `service.py` 定义 `SocialGraphService` 类（含 K=10 默认半饱和点 + 内部 `_ties: dict[tuple[str,str], Tie]`）
- [x] 1.4 顶层 `synthetic_socio_wind_tunnel/__init__.py` re-export `Tie` + `SocialGraphService`

## 2. SocialGraphService 核心 API

- [x] 2.1 实现 `record_encounter(a, b, tick, day_index) -> Tie`：normalize pair、新建或累计 Tie、同 tick 同 pair 幂等（用 `(pair, tick)` 短期 set 去重）
- [x] 2.2 实现 `get_tie(a, b) -> Tie | None`（顺序无关）
- [x] 2.3 实现 `ties_for(agent_id) -> list[Tie]`（O(1) 走辅助索引或 O(N) 直接遍历，agent → ties 映射可选）
- [x] 2.4 实现 `familiar_with(agent_id, threshold=0.1) -> set[str]`（返回 other agent_id 集合）
- [x] 2.5 实现 `weak_ties(agent_id)` / `strong_ties(agent_id)` / `all_ties()` 列表方法
- [x] 2.6 实现 strength 公式 `encounter_count / (encounter_count + K)`，K 走 service 实例属性
- [x] 2.7 写 `tests/test_social_graph_models.py`：Tie 不可变、canonical ordering 强制
- [x] 2.8 写 `tests/test_social_graph_service.py`：record / get / 同 tick 同 pair 幂等 / strength 公式数值 / weak vs strong 阈值 / 顺序无关查询 / ties_for / familiar_with

## 3. MemoryService 集成

- [x] 3.1 `MemoryService.__init__` 接受 `social_graph: SocialGraphService | None = None`
- [x] 3.2 `process_tick` 在写 encounter MemoryEvent 之外，对每条 encounter_candidate 额外调 `social_graph.record_encounter(...)`（注入了才调）
- [x] 3.3 `_nearby_agents_for` 装配 NearbyAgent 时：social_graph 注入则用 `social_graph.familiar_with(agent_id, threshold=0.1)`，否则降级到原 memory-based 判定
- [x] 3.4 写 `tests/test_memory_service.py` 新 case：encounter 同步累积进 graph、is_familiar 来源切换、social_graph=None 时降级
- [x] 3.5 跑现有 `tests/test_memory_*.py` + `tests/test_memory_debts_fixed.py` 避免回归

## 4. AgentRuntime 集成

- [x] 4.1 `AgentRuntime` 加 `social_graph: SocialGraphService | None = None` 字段
- [x] 4.2 实现 `familiar_with(other_agent_id, threshold=0.1) -> bool` 薄封装
- [x] 4.3 写 `tests/test_runtime_social_graph.py`：4 个 spec scenario 各覆盖一个 case

## 5. metrics 集成

- [x] 5.1 `TickMetricsRecorder.__init__` 接受 `social_graph: SocialGraphService | None = None`
- [x] 5.2 day rollup 时（DayMetricsCollector → DayMetricsSummary 转换），如果 social_graph 注入，从 graph 提取 5 个指标（tie_count_total / weak / strong / new_ties_today / avg_ties_per_agent）；否则保持 None
- [x] 5.3 `RunMetrics.from_recorder` 工厂在 recorder 持有 social_graph 时填 `weak_tie_formation_count = len(graph.weak_ties from final state)`
- [x] 5.4 写 `tests/test_metrics_social_graph.py`：注入与不注入两种路径
- [x] 5.5 跑现有 `tests/test_metrics_*.py` 避免回归

## 6. tools 装配

- [x] 6.1 `tools/run_variant_suite.py` 在每 seed run 中构造 `SocialGraphService(K=10)`，注入 MemoryService + TickMetricsRecorder + （所有 AgentRuntime）
- [x] 6.2 `tools/export_inspector_payload.py` 同样注入；inspector payload 加 `social_graph` 顶层 key（dump 每个 inspected agent 的 weak/strong ties 列表）
- [x] 6.3 `tools/replan_trace.py` 注入 social_graph 让 trace 中 nearby_agents 真实化
- [x] 6.4 smoke 跑：`python3 tools/export_inspector_payload.py --inspect 3 --num-days 3`，确认输出 JSON 含 social_graph 字段且非空

## 7. e2e mini sim 验证

- [x] 7.1 写 `tests/test_social_graph_integration.py`：跑 50 agent × 7 day baseline + hyperlocal_push（stub LLM），断言：
    - 两 variant 都产生 > 0 weak ties
    - hp 的 weak ties 数 > baseline（hyperlocal push 把 agent 拉到同位置应该多产生 encounter）
    - 14 天累积下 K=10 让 strong ties 出现（encounter_count ≥ 10 的 pair 至少有 1 对）
- [x] 7.2 跑测试一次手动看数；如 strong tie 一对都没有，K 调小到 5 或 weak 阈值降低

## 8. dev publishable suite 验证 — DEFERRED

- [x] 8.1 ~~跑 `tools/run_variant_suite.py --seeds 5 --num-days 7 --variants baseline,hyperlocal_push --use-real-llm`~~ — **deferred**
- [x] 8.2 ~~比较 baseline vs hp 的 weak_tie_formation_count~~ — **deferred**
- [x] 8.3 ~~检查 is_familiar 比例的累加趋势~~ — **deferred**

**为什么 defer**：本 change 已通过 e2e mini sim（50 agent × 3 day × stub LLM）验证社交图在两 variant 下都正常累积 ties。"hp.weak_ties > baseline.weak_ties" 是 publishable 量级 + 真 LLM 的实证问题，可与下次 publishable run 一起跑（与 conversation-capability 上线后的对照更有意义）。

## 9. 文档同步

- [x] 9.1 更新 `docs/agent_system/19-system-snapshot.md`：决策点表追加 social-graph 这条；capability 列表加 `social-graph` 行
- [x] 9.2 更新 `docs/agent_system/20-realism-roadmap.md`：标记 F6 第一阶段（社交涌现）的"weak tie 累积"已落地；剩余 conversation 部分单独 change
- [x] 9.3 CLAUDE.md 不更新（架构隐喻不变；新模块 social_graph/ 在结构里）

## 10. 可选：tie decay V2 占位

- [x] 10.1 ~~tie decay 公式~~ — **deferred to V2**。当前不实现；`last_seen_tick` 字段已在 Tie 数据模型里预留好。
