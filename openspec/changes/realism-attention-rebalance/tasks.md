## 1. ReplanDecisionRecord 数据模型

- [x] 1.1 在 `synthetic_socio_wind_tunnel/agent/runtime.py` 新增 frozen Pydantic `ReplanDecisionRecord`（字段见 specs/agent/spec.md）
- [x] 1.2 `AgentRuntime` 新增 `enable_replan_log: bool = False` + `replan_decision_log: list[ReplanDecisionRecord]`，默认空
- [x] 1.3 `__init__.py` 加 ReplanDecisionRecord re-export

## 2. NearbyAgent 数据模型

- [x] 2.1 在 `synthetic_socio_wind_tunnel/agent/intent.py`（或新文件 `runtime_ctx.py`）新增 frozen Pydantic `NearbyAgent { is_familiar: bool }`
- [x] 2.2 `__init__.py` 加 NearbyAgent re-export

## 3. AgentRuntime.should_replan 重构

- [x] 3.1 改 `should_replan` 签名加上 `current_step` / `replan_count_today` / `rng` 参数，保持向后兼容（可选参数）
- [x] 3.2 实现 6 维 personality + context modifier + 疲劳衰减的 base 公式（设计 D2）
- [x] 3.3 实现概率门：`rng.random() + (urgency - threshold) > 0`
- [x] 3.4 实现 `enable_replan_log=True` 时往 replan_decision_log 追加 ReplanDecisionRecord
- [x] 3.5 写 `tests/test_should_replan_rebalanced.py`：6 维 personality 各加分项独立可观测、context modifier 工作、疲劳衰减工作、概率门让同 urgency 不全 0/1
- [x] 3.6 跑 `tests/test_runtime_phase1.py`（避免回归）

## 4. AgentRuntime.elapsed_in_step 暴露

- [x] 4.1 `AgentRuntime` 已持有 `_current_step_started_at`，加只读 property `current_step_elapsed_min` 计算分钟数
- [x] 4.2 单测覆盖：start_at 为 None 时返回 0；正常情况返回正确分钟

## 5. MemoryService.process_tick interrupt_ctx 装配

- [x] 5.1 MemoryService 新增 per-agent `_replan_count_today` dict，process_tick 末根据 day_index 变化清零
- [x] 5.2 新增 helper：从 `ledger.get_entity(aid).location_id` 反查 `atlas` 的 area_type，归一化为 6 类（"street"/"cafe"/"park"/"home"/"office"/"other"）
- [x] 5.3 新增 helper：从 tick_result.encounter_candidates + agent memory 装配 `nearby_agents: list[NearbyAgent]`（is_familiar 通过 actor_id 是否在历史 encounter MemoryEvent 中判定）
- [x] 5.4 process_tick 调 `should_replan(... current_step, replan_count_today, rng=self._rng)`
- [x] 5.5 process_tick 调 `planner.replan(profile, current_plan, interrupt_ctx)` 时传完整新 schema 的 interrupt_ctx
- [x] 5.6 写 `tests/test_memory_service.py` 新 case：装配的 interrupt_ctx 含 5 个新 key、replan_count_today 跨日重置、rng 来源稳定

## 6. Planner._build_replan_prompt 重构

- [x] 6.1 重写 `_build_replan_prompt` 实现"对称 context window"模板（设计 D1 + specs/agent Requirement: Replan prompt 对称 context window）
- [x] 6.2 实现空 block 整块省略逻辑
- [x] 6.3 prompt 中性化：移除"打断"/"interrupt"/"紧急"等措辞
- [x] 6.4 写 `tests/test_replan_prompt_structure.py`：
    - prompt 含 6 个 `【...】` block 标记（数据完整时）
    - prompt 不含 banned 措辞列表
    - nearby_agents=[] 时整块省略
    - current_step=None 时整块省略

## 7. Planner.replan interrupt_ctx 兼容

- [x] 7.1 `replan` 接受 interrupt_ctx 缺新 key 的旧 caller，安全降级
- [x] 7.2 写 `tests/test_planner.py` 新 case：旧 schema interrupt_ctx 不抛、新 schema 完整时全 6 block 进 prompt

## 8. 触发率 goldilocks 回归

- [x] 8.1 新增 `tests/test_attention_rebalance_e2e.py`，跑 100 agent × 100 rng × hyperlocal_push 候选（轻量版本，无完整 sim）
- [x] 8.2 测 1：100 agent 平均触发率 ∈ [5%, 15%]
- [x] 8.3 测 2：100 agent 触发率分布 ≥ 3 个 bin 有 ≥5 agents（heterogeneity）
- [x] 8.4 测 3：低 adherence 簇 vs 高 adherence 簇均值差异显著

## 9. fitness-audit 触发率探针 — DEFERRED

- [ ] 9.1 ~~在 `synthetic_socio_wind_tunnel/fitness/audits/` 新增 audit~~ — **deferred**
- [ ] 9.2 ~~SuiteAggregate 反查 replan rate 报 warning~~ — **deferred**
- [ ] 9.3 ~~audit 测试~~ — **deferred**

**为什么 defer**：spec 的 goldilocks band 约束已经被 `tests/test_attention_rebalance_e2e.py::TestGoldilocksBand` 在单元层强制。fitness audit 是 suite 级别的二次防线，等真出现 suite 级越界事件再做更稳。

## 10. inspector payload 接入决策日志

- [x] 10.1 改 `tools/export_inspector_payload.py`，runtime 启动前设 `runtime.enable_replan_log = True`
- [x] 10.2 末尾收集 `replan_decision_log` 写入 payload 顶层 key
- [x] 10.3 跑 smoke：`python3 tools/export_inspector_payload.py --inspect 3 --num-days 3`（stub LLM dev smoke），确认 `replan_decision_log` 长度 > 0（实际 4 条 decision 落盘）

## 11. dev publishable suite 验证

- [x] 11.1 跑 `tools/run_variant_suite.py --seeds 5 --num-days 7 --variants baseline,hyperlocal_push,global_distraction --use-real-llm`（41min wall, Gemini Flash）→ `data/experiments/20260505_131019_attn_rebalance_validation/`
- [x] 11.2 hp encounter shift v2(-34%)→v3(-14%)，方向正确（小于 v2 → 压住 prompt artifact）
- [x] 11.3 hp CI 宽度 v2 5732 → v3 6742，略宽（5 seed vs 30 seed sample size 差异，非机制噪音）
- [x] 11.4 三次对比写入 commit message（v1 -18% / v2 -34% / v3 -14%；hp.traj_dev < gd.traj_dev 三次一致）

## 12. 文档同步

- [x] 12.1 更新 `docs/agent_system/19-system-snapshot.md` 决策点表（追加 2026-04-29 这条）
- [x] 12.2 更新 `docs/agent_system/20-realism-roadmap.md`：标记原 Stage 3 为已被 attention-rebalance 取代；调整后续 stage 描述
- [x] 12.3 CLAUDE.md 不需要更新（架构不变 / API surface 不变）

## 13. 可选：v1 prompt 回滚 flag — SKIPPED

- [x] 13.1 ~~回滚 flag~~ — **skipped** per design Migration Plan: 等 Task 11 验证后再决定，目前无证据需要它
- [x] 13.2 ~~跳过此组~~ — **done**：保持单一版本
