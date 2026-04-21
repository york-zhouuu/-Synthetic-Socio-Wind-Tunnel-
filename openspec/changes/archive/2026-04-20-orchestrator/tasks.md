## 1. Intent 层次（agent 模块）

- [x] 1.1 创建 `synthetic_socio_wind_tunnel/agent/intent.py`：定义 `Intent` 基类 + 7 个子类（MoveIntent / WaitIntent / ExamineIntent / PickupIntent / OpenDoorIntent / UnlockIntent / LockIntent）
- [x] 1.2 每个 Intent 子类暴露 `exclusive: bool` property；独占型暴露 `target_id: str` property
- [x] 1.3 所有 Intent frozen + 可哈希（用 `@dataclass(frozen=True)` 或 Pydantic `ConfigDict(frozen=True)`，与既有 attention 模型风格一致）
- [x] 1.4 写 `tests/test_agent_intent.py`：构造、frozen、哈希、exclusive/target_id 属性

## 2. AgentRuntime.step

- [x] 2.1 在 `agent/runtime.py` 追加 `step(tick_ctx) -> Intent` 方法
- [x] 2.2 映射规则（见 design D10）：move + current!=destination → MoveIntent；move + current==destination → WaitIntent("at_destination")；其它 action → WaitIntent(activity)；plan 空/耗尽 → WaitIntent("plan_exhausted")
- [x] 2.3 内部自动 advance：检查 `simulated_time >= step.time + step.duration_minutes` 时调 `self.plan.advance()`；orchestrator 不得直调
- [x] 2.4 本 change **不**产出 Examine/Pickup/OpenDoor/Unlock/Lock——类型存在但 step() 只吐 Move/Wait
- [x] 2.5 `agent/__init__.py` re-export Intent 基类与 7 个子类
- [x] 2.6 扩展 `tests/test_agent_intent.py`：plan 映射、到达目的地保留 WaitIntent、时间窗过期自动 advance、计划耗尽
- [x] 2.7 确认 `tests/test_agent_phase1.py` 全部仍 PASS

## 3. Orchestrator 数据模型

- [x] 3.1 创建 `synthetic_socio_wind_tunnel/orchestrator/` 目录，含 `__init__.py`
- [x] 3.2 定义 `TickContext`（frozen dataclass，带 tick_index / simulated_time / observer_context）
- [x] 3.3 定义 `CommitRecord`（agent_id / intent / result: SimulationResult）
- [x] 3.4 定义 `EncounterCandidate`（frozen：tick / agent_a / agent_b / shared_locations）
- [x] 3.5 定义 `TickResult`（frozen：tick_index / simulated_time / commits tuple / encounter_candidates tuple）
- [x] 3.6 定义 `SimulationContext` / `SimulationSummary`（frozen）
- [x] 3.7 写 `tests/test_orchestrator_models.py`：frozen、可哈希、序列化

## 4. IntentResolver

- [x] 4.1 创建 `orchestrator/intent_resolver.py`，实现 `IntentResolver.resolve(intent_pool: dict[agent_id, Intent]) -> list[CommitDecision]`
- [x] 4.2 非独占 Intent 直接进入提交队列
- [x] 4.3 独占 Intent 按 target_id 分组，同组内按 agent_id 字典序取赢家；失败者记录 "lost_to: winner_id"
- [x] 4.4 产出 `CommitDecision(agent_id, intent, status: Literal["commit", "rejected"], reason)`
- [x] 4.5 写 `tests/test_intent_resolver.py`：两人抢伞、多人抢门、非独占不触发裁决

## 5. Orchestrator 主循环

- [x] 5.1 创建 `orchestrator/service.py`，实现 `Orchestrator.__init__` 按 D7 签名
- [x] 5.2 默认填充 simulation / pipeline / navigation（若未提供）
- [x] 5.3 `num_days > 1` 构造即 raise NotImplementedError
- [x] 5.4 `tick_minutes` 必须为正整数且 1440 % tick_minutes == 0，否则 raise ValueError；计算 `ticks_per_day = 1440 // tick_minutes`
- [x] 5.5 实现 `run() -> SimulationSummary`：按 D4 顺序执行 (2+4+5)+6+hook(1,7)
- [x] 5.6 tick 内 observer_context 构造：从 `AgentRuntime.build_observer_context()` 拿 dict + 从 `Ledger.get_entity(agent_id).position` 补 `position` 字段，合并后构造 `ObserverContext` 实例（D11）
- [x] 5.7 Intent → SimulationService 分派：MoveIntent→move_entity (逐 step)；WaitIntent→无操作直接 ok；Pickup→give_item_to_entity；OpenDoor→open_door；Unlock→unlock_door；Lock→lock_door；Examine→mark_item_examined
- [x] 5.8 写 `tests/test_orchestrator_tick_loop.py`：单 tick / 288 tick / plan 耗尽后仍可跑 / Intent 类型 → SimulationService 分派正确

## 6. 子 tick 轨迹插值 + 逐 step Ledger 写

- [x] 6.1 在 Orchestrator 内部维护 `_current_tick_traces: dict[agent_id, TickMovementTrace]`
- [x] 6.2 MoveIntent commit 阶段：调 `NavigationService.find_route(from, to)`
- [x] 6.3 对 `NavigationResult.steps` 的每个 location，依次调 `SimulationService.move_entity(agent_id, step_location)`；Ledger `current_time` 在 sub-step 之间不推进
- [x] 6.4 每次 sub-step 成功后 append 到 `TickMovementTrace.locations`；失败即停止后续 sub-step 并记录失败 result
- [x] 6.5 CommitRecord.result 对多 sub-step 整合：全成功 = 最后 step 的 success 结果；中途失败 = 失败那一 step 的 result
- [x] 6.6 实现 `_detect_encounters() -> list[EncounterCandidate]`：按 location 分桶 O(total_len)；`shared_locations = tuple(sorted(intersection))` 确保确定性
- [x] 6.7 tick 末清空 trace；encounters 传给 `on_tick_end` 订阅者
- [x] 6.8 写 `tests/test_orchestrator_encounters.py`：3-step 路径写 3 次 move_entity / sub-step 中途失败 / 街道段交汇 / 仅终点不算 / MoveIntent 第一步失败无 trace

## 7. Hook 系统

- [x] 7.1 定义 `HookRegistry`（内部 dict of callback lists）
- [x] 7.2 暴露 4 个注册方法：`register_on_simulation_start / _tick_start / _tick_end / _simulation_end`
- [x] 7.3 触发顺序：按注册顺序同步调用；callback 异常原样向上传播
- [x] 7.4 写 `tests/test_orchestrator_hooks.py`：多订阅者顺序、异常终止 simulation

## 8. 确定性 & seed

- [x] 8.1 Orchestrator 接受 `seed: int = 0`，传给 IntentResolver 预留
- [x] 8.2 写 `tests/test_orchestrator_determinism.py`：相同 seed 两次 run → `ledger.to_dict()` 逐字段相等

## 9. 公共 API & 回归

- [x] 9.1 `synthetic_socio_wind_tunnel/__init__.py` re-export `Orchestrator` / `TickContext` / `TickResult` / `EncounterCandidate` / 所有 Intent 类
- [x] 9.2 跑 `python3 -c "from synthetic_socio_wind_tunnel import Orchestrator, MoveIntent; print('OK')"` 确认
- [x] 9.3 跑全量 `python -m pytest tests/ -v`，Phase 1 / 1.5 所有测试仍 PASS
- [x] 9.4 跑 `make fitness-audit`：确认 `phase2-gaps.orchestrator` 由 FAIL 转 PASS；`scale-baseline` 的 wall time 相对 Phase 1.5 基线 SHOULD 上升 3-10x（预期；逐 step 写 Ledger 的代价）
- [x] 9.5 若 `scale.wall-time` 在 quick-scale 下 FAIL（>120s），先不做并发优化，而是检查 `SimulationService.move_entity` 的事件生成有没有冗余
- [x] 9.6 （可选）跑 `make fitness-audit-full`：实测 1000×288 orchestrator 单天耗时

## 10. Archive 前

- [x] 10.1 `openspec validate orchestrator` 无错误
- [x] 10.2 手动在 Lane Cove atlas 上写一个 smoke demo：5 agents × 72 tick，观察至少 1 个 encounter 产出
- [x] 10.3 文档：在 `docs/agent_system/` 下新增 `08-orchestrator-tick-loop.md`（一页：tick 内顺序 + Intent 分类 + hook 契约）
