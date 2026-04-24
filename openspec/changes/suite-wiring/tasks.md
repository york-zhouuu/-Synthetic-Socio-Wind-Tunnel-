# Tasks — suite-wiring

补 `run_variant_suite.py` 缺失的 variant → memory → replan 因果链。
无新 capability、无已归档 spec 改动；纯 CLI + helper + tests。

**Chain-Position**: `infrastructure`（CLI wiring 修补）
**前置**: `metrics` / `policy-hack` / `multi-day-simulation` / `memory` /
`attention-channel` / `agent` 全部已归档（只用既有公共 API）

## 1. StubReplanLLM helper

- [ ] 1.1 新建 `tools/suite_stub_llm.py`：
  - `StubReplanLLM` class（实现 `LLMClient` 协议）
  - `__init__(*, seed, variant_name, target_location)`
  - `async generate(prompt, *, model="", **_) -> str` 按 variant_name dispatch
  - 内部 helper `_plan_toward(location, *, rng)` 生成走向 loc 的 PlanStep JSON
  - `_SHARED_ANCHOR_LOC_HEURISTIC(atlas, destinations)` 选 community loc
- [ ] 1.2 输出 JSON 格式与 Planner.replan 的 parse 一致（含 time /
  action / destination / activity / duration_minutes / reason /
  social_intent 七字段）

## 2. run_variant_suite.py CLI 整合

- [ ] 2.1 import MemoryService / Planner / StubReplanLLM
- [ ] 2.2 `run_seed_with_metrics` 构造：
  - 一个 MemoryService（attention_service=attention_service）
  - 一个 StubReplanLLM（或 real LLM，若 --use-real-llm）
  - 一个 Planner(llm_client=stub_llm)
  - 注册 `orchestrator.on_tick_end` 两条 hook：
    1. `recorder.on_tick_end`（已有）
    2. `lambda tr: memory.process_tick(tr, agents_by_id, planner)`（新）
- [ ] 2.3 累加 `memory.process_tick` 返回的 replan list：
  - 跨 tick 累加到 `replan_by_day: list[int]`（长度 num_days）
  - 跨 day 汇总 `replan_count`
  - run 结束后 `run_metrics = run_metrics.with_extensions(replan_count=...,
    replan_by_day=...)`
- [ ] 2.4 新 `--use-real-llm` flag：
  - default False
  - True 时用 `_make_llm_client(use_real=True, ...)` 构 Anthropic 客户端
  - anthropic SDK 未安装则 exit(1) 加提示

## 3. Real-LLM 客户端（最小 wrap）

- [ ] 3.1 `tools/suite_stub_llm.py` 加 `_AnthropicClient`（或同目录 helper）：
  - `__init__(self, *, model="claude-haiku-4-5-20251001")`
  - `async generate(prompt, *, model="", **_) -> str` 调 Anthropic messages API
  - 最小实现；无 retry / cost 控制（留给未来 model-budget）

## 4. 测试

- [ ] 4.1 `tests/test_suite_stub_llm.py`：
  - hyperlocal_push stub 产出含 destination==target 的 JSON
  - global_distraction stub 返回 "[]"
  - shared_anchor stub 产出含 community heuristic location 的 JSON
  - 未知 variant_name fallback "[]"
  - 同 seed 构造两次 → generate 输出 byte-equal
  - Planner.replan 接受 stub 产出（parse 不抛、返回合法 DailyPlan）
- [ ] 4.2 `tests/test_suite_wiring.py`：
  - `TestReplanCountPropagation`:
    - baseline 3 天 run 的 extensions["replan_count"] == 0
    - hyperlocal_push 3 天 run 的 replan_count > 0
    - 各 seed 的 `sum(replan_by_day) == replan_count`
  - `TestBehavioralDifference`:
    - 2 seed × 3 day × 20 agent 跑 baseline / hyperlocal_push /
      global_distraction
    - 断言 `hp.trajectory_deviation_m < gd.trajectory_deviation_m`
    - 断言 `hp.replan_count > 0` and `bl.replan_count == 0`
  - `TestRealLLMFlag`:
    - 不传 `--use-real-llm` → subprocess exit 0，无 anthropic import 错误
    - 传 `--use-real-llm` 且系统无 anthropic SDK → exit != 0（用
      `ANTHROPIC_FORCE_MISSING` env 或 monkeypatch 模拟）

## 5. 文档

- [ ] 5.1 新建 `docs/agent_system/17-suite-wiring.md`：
  - 因果链图（variant → AttentionService → MemoryService → should_replan
    → Planner → AgentRuntime.plan → AgentRuntime.step → Ledger → Recorder
    → RunMetrics）
  - StubReplanLLM 的 variant dispatch 表（+ 各 variant 预期行为）
  - `--use-real-llm` 使用说明 + cost 警告
  - 与 metrics/policy-hack/multi-day-run/memory 的关系
  - smoke 示例：3 day × 2 seed × 20 agent 跑 baseline + hyperlocal_push +
    global_distraction，期望输出示例
- [ ] 5.2 更新 `README.md` Development Status：加 "Suite wiring
  (variant→replan 因果链)" ✅
- [ ] 5.3 更新 `docs/agent_system/16-metrics.md` 的 "已知限制" 段：
  - 移除 "variant 不影响 agent 行为" 的讨论（现已修）
  - 加一行指向 `17-suite-wiring.md`

## 6. 回归 + smoke

- [ ] 6.1 全 pytest 回归：零 Phase 1 / Phase 2 / metrics / policy-hack 失败
- [ ] 6.2 6-variant × 2 seed × 3 day smoke：
  `python3 tools/run_variant_suite.py --variants baseline,hyperlocal_push,
  global_distraction,phone_friction,shared_anchor,catalyst_seeding --seeds 2
  --num-days 3 --agents 20 --mode dev --phase-days 1,1,1 --suite-name wiring_smoke`
  - 读 contest.json：hyperlocal_push 的 primary_effect_size ≠
    global_distraction 的（即 trajectory_deviation_m 现在有差异）
  - 读 seed_42.json：run_metrics.extensions 含 replan_count

## 7. 性能

- [ ] 7.1 14 day × 100 agent × 1 seed wall time ≤ 35s
  （metrics-only 12s + memory.process_tick × 14 day × 288 tick × 100 agent
  期望 < 15s 额外；总 < 35s）

## 8. 验证

- [ ] 8.1 `openspec validate suite-wiring --strict` 通过
- [ ] 8.2 grep 检查 `synthetic_socio_wind_tunnel/` 无任何 `.py` 文件 diff
  （只改 tools/ 与 docs/ + tests/）
- [ ] 8.3 grep 检查 `openspec/specs/` 下已归档 spec 文件无 diff
