## 1. inspector CLI（最小独立，先做）

- [x] 1.1 新建 `tools/agent_perception_inspector.py`：argparse + 加载 atlas + 重建 ledger 到指定 (seed, day, tick) → 用 `AgentRuntime.build_observer_context()` + `PerceptionPipeline.render()` 出 SubjectiveView
- [x] 1.2 实现 prose 输出（标题 / Location / Visible / Audible / Digital / JSON）
- [x] 1.3 新增 `tests/test_perception_inspector_cli.py`：(a) smoke 跑通输出 4 个 section；(b) 不存在 agent_id 时 exit ≠ 0 且 stderr 含 actionable
- [x] 1.4 跑 `pytest tests/test_perception_inspector_cli.py -v`，过

## 2. SubjectiveView → prose helper（被 Planner + inspector 共用）

- [x] 2.1 新增 `synthetic_socio_wind_tunnel/perception/prose.py::render_subjective_view_prose(view: SubjectiveView) -> str`：把 visible_entities / audible_events / olfactory_descriptors 拼成 ≤ 200 字中文 prose
- [x] 2.2 处理空 view：返回空字符串（不返"环境平静无奇"等占位文本）
- [x] 2.3 处理 crowd 信息：count 同 location 的 agent，prose 含数字
- [x] 2.4 新增 `tests/test_perception_prose.py`：(a) 空 view 返空字符串；(b) 5 个 visible agent 时 prose 含 "5"；(c) item 的 content 出现在 prose 里；(d) 文本 ≤ 200 字
- [x] 2.5 跑测试，过

## 3. Planner.replan 加 perceptual_context kwarg + 【环境】 block

- [x] 3.1 修改 `Planner.replan` 签名：增加 `*, perceptual_context: SubjectiveView | None = None`
- [x] 3.2 修改 `_build_replan_prompt`：增加 `perceptual_view` 参数；在 `【手机】` block 之后插入 `【环境】` block（用 §2 的 prose helper）；空 view 整块省略
- [x] 3.3 grep planner.replan 现有 callers（memory.process_tick + tests）：保持不变（默认 None 兼容）
- [x] 3.4 新增 `tests/test_planner_perception_block.py`：(a) 不传 perceptual_context → prompt 不含 `【环境】`；(b) 传 view → prompt 含 `【环境】`；(c) 视觉 / 听觉 / 嗅觉至少一个出现在 block 里
- [x] 3.5 跑 `pytest tests/test_planner* -v`，过（含原有 replan prompt structure 测试）

## 4. AgentRuntime.step 在 replan 触发前 render perception

- [x] 4.1 修改 `AgentRuntime.step`（或 process_tick / 等同方法）：在 `should_replan` 评估为 True 后、调 `planner.replan` 前，调 `self._perception.render(observer_ctx)` 取 SubjectiveView，传给 replan 的 `perceptual_context` kwarg
- [x] 4.2 处理 perception 未注入：`if self._perception is None` 跳过 render，perceptual_context=None
- [x] 4.3 注意：当前 replan 是在 `memory.process_tick` 中触发的，不是在 `AgentRuntime.step` —— 需要在 memory.process_tick 调 planner.replan 前从 agent 拿 perceptual_context（addBlockedBy 关注：可能要改 memory.service 接口）
- [x] 4.4 新增 `tests/test_agent_runtime_perception_in_replan.py`：注入 perception → replan 收到的 prompt 含 `【环境】`；不注入 → 不含
- [x] 4.5 跑 `pytest tests/ -k "memory or planner or runtime"`，过

## 5. Scripted plan 抵达后的 perception-gated destination-swap

- [x] 5.1 新增 `agent/scripted_plan.py::perception_gated_destination_swap(current_step, observer_ctx, rng, atlas, *, crowd_threshold=5) -> str | None` —— 同 area_type / hyperlocal 1000m 范围 / 不选 home
- [x] 5.2 修改 `AgentRuntime.step` 的 stay-arrived 分支：non-protag + 注入 perception + 抵达 → 调 swap helper；返回非 None 时改写 plan step destination + reset arrival_minute
- [x] 5.3 新增 `tests/test_scripted_plan_perception_gate.py`：6 个 scenario（拥挤+高 openness → swap；拥挤+低 openness 多次抽样 → 大概率不 swap；不拥挤 → 不 swap；protag → 不走此路径；hyperlocal 范围内选；同 area_type 优先）
- [x] 5.4 跑测试，过

## 6. 端到端 smoke 验证

- [x] 6.1 跑 `python3 tools/run_variant_suite.py --seeds 1 --num-days 1 --agents 20 --variants baseline,hyperlocal_push --mode dev --suite-name perception_smoke --phase-days 0,1,0`，走通
- [x] 6.2 inspect smoke 输出 / debug log，确认：(a) 至少 1 个 protag 的 replan prompt log 含 `【环境】` 字符串；(b) 至少 1 个 scripted agent 因 crowd-gate 换了 destination（看 plan step.destination diff）
- [x] 6.3 写 `tests/test_perception_loop_e2e.py`：把 6.1 同样配置封装成 pytest，断言 6.2 的两条性质
- [x] 6.4 跑 `pytest tests/test_perception_loop_e2e.py -v`，过

## 7. 全量回归 + 阈值校准

- [x] 7.1 跑 `pytest tests/`，断言 1190+ passed（预期 +10..15 新测试）
- [x] 7.2 如 realism test 因 swap-rate 偏移失败 → 用 round-2 同款方式校准阈值，附中文注释
- [x] 7.3 性能 spot-check：1 day × 20 agent smoke wall-clock 与 fix-encounter-detection-and-observability 同配置 baseline 对比（额外 ≤ 50ms / tick）
- [x] 7.4 跑 `openspec validate realism-perception-loop --strict`，过

## 8. Sync + Archive

- [x] 8.1 sync `agent` spec delta 到 main spec
- [x] 8.2 final regression `pytest tests/`，过
- [x] 8.3 final `openspec validate realism-perception-loop --strict` + `openspec validate agent --strict`，过
- [x] 8.4 archive 到 `openspec/changes/archive/2026-MM-DD-realism-perception-loop/`
- [x] 8.5 在 `docs/agent_system/20-realism-roadmap.md` Stage 2 节追加 ✅ ARCHIVED 标记 + 日期
