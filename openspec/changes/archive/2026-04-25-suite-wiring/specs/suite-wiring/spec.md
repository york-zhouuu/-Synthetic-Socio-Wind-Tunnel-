## ADDED Requirements

### Requirement: Suite CLI SHALL wire MemoryService + Planner 到 orchestrator

`tools/run_variant_suite.py::run_seed_with_metrics` SHALL 在 orchestrator
栈里构造以下组件并把它们串进 `on_tick_end` hook 链：

1. `AttentionService`（policy-hack variant push 到此）
2. `MemoryService(attention_service=attention)`
3. `Planner(llm_client=<stub 或 real>)`
4. `TickMetricsRecorder(ledger, attention_service)`

Tick 结束时执行顺序：
```
orchestrator._run_tick → on_tick_end hook chain:
  recorder.on_tick_end(tick_result)                      # 观察，不改状态
  memory.process_tick(tick_result, agents, planner)      # 触发 replan
```

#### Scenario: 带 variant 的 run 触发非零 replan_count
- **WHEN** `run_seed_with_metrics(variant_name="hyperlocal_push", seed=0,
  n_agents=20, num_days=3, ...)` 执行
- **THEN** 返回的 RunMetrics.extensions SHALL 含 `replan_count`，值 SHALL > 0

#### Scenario: baseline 不触发 replan
- **WHEN** `run_seed_with_metrics(variant_name="baseline", ...)`
- **THEN** `replan_count` SHALL == 0（无 feed 注入 → 无 notification →
  should_replan 不通过）


### Requirement: StubReplanLLM 按 variant_name 分派行为

`tools/suite_stub_llm.py::StubReplanLLM` SHALL 是 `LLMClient` 协议的纯
Python 实现；`__init__(*, seed, variant_name, target_location)` 接收
variant 身份与目标位置；`generate(prompt, *, model)` **忽略 prompt 内容**，
按 variant_name 返回预定的 JSON plan 片段：

| variant_name | Stub 响应 |
|---|---|
| `hyperlocal_push` | 含 1 条 PlanStep 走向 target_location（action="move"） |
| `global_distraction` | `"[]"`（空）——证明 global news 不拉 scripted agent |
| `shared_anchor` | 走向 community heuristic location（park/plaza 或 destinations[0]） |
| `phone_friction` / `catalyst_seeding` / 未知 | `"[]"` |

输出 SHALL 是 Planner.replan 可解析的 JSON 格式；stub **MUST NOT** 调用任何
外部 LLM / 网络。

#### Scenario: hyperlocal_push stub 产出包含 target
- **WHEN** 构造 `StubReplanLLM(seed=0, variant_name="hyperlocal_push",
  target_location="cafe_main")`；调 `generate("any prompt")`
- **THEN** 返回字符串 SHALL JSON-parse 为 list；至少一个 step 的
  `destination == "cafe_main"`；action=="move"

#### Scenario: global_distraction stub 返回空
- **WHEN** 构造 `StubReplanLLM(variant_name="global_distraction", ...)`；
  调 `generate`
- **THEN** 返回 SHALL `== "[]"`；Planner.replan 在此输入下 SHALL 保持原
  DailyPlan 不变（或返回空 steps）

#### Scenario: 跨 seed reproducibility
- **WHEN** 两次分别构造同 seed 的 StubReplanLLM；各调 generate 3 次
- **THEN** 两组返回 SHALL byte-equal


### Requirement: --use-real-llm 切换 LLM provider

`run_variant_suite.py` SHALL 接受 `--use-real-llm` flag（默认 False）；
True 时 planner 的 llm_client SHALL 为 `anthropic.Anthropic` 包装（若
`anthropic` 未安装 → 启动时清楚错误退出）；False 时走 StubReplanLLM。

#### Scenario: 默认不走真 LLM
- **WHEN** `python3 tools/run_variant_suite.py --variants baseline ...`（无
  `--use-real-llm`）
- **THEN** run 过程 SHALL 不触发任何外部 HTTP 调用；可离线跑

#### Scenario: --use-real-llm 未装 anthropic
- **WHEN** `anthropic` SDK 未安装；传 `--use-real-llm`
- **THEN** CLI SHALL exit with code != 0；stderr 含可 actionable 安装提示


### Requirement: Replan 计数写入 RunMetrics.extensions

每个 seed 的 RunMetrics SHALL 通过 `with_extensions` 携带以下键：
- `replan_count: int`（全 run 总 replan 次数）
- `replan_by_day: list[int]`（per-day replan 计数，长度 == num_days）

不得新增 RunMetrics 的 typed 字段（metrics spec 明文 extensions 作未来
挂载点）。

#### Scenario: replan_count 等于 by_day 之和
- **WHEN** 一个 14 day run 的 RunMetrics dump
- **THEN** `extensions["replan_count"] == sum(extensions["replan_by_day"])`

#### Scenario: Dump 到 seed_<N>.json
- **WHEN** `run_variant_suite.py` 跑完一个 seed
- **THEN** `seed_<N>.json` 中 `run_metrics.extensions` SHALL 含
  `replan_count` 与 `replan_by_day`


### Requirement: 行为差异最小要求

suite-wiring change 的实施结果 SHALL 让以下行为差异在 3 day × 2 seed ×
20 agent × 默认 variant 配置下可被 E2E 测试验证：

- `hyperlocal_push` variant 的 `trajectory_deviation_m` **median
  显著小于** `global_distraction` variant 的 `trajectory_deviation_m`
  median（即：push 确实把 target agents 拉向 target_location，global news 
  不拉）
- `hyperlocal_push` 的 `replan_count` SHALL > 0
- `baseline` 的 `replan_count` SHALL == 0

**阈值**：`push < distraction`（方向正确即可，不做 CI 分离检查——本 change
目标是因果链通，严谨 CI 由 publishable 30 seed × 14 day 产出）。

#### Scenario: E2E 断言行为可区分
- **WHEN** `pytest tests/test_suite_wiring.py::TestBehavioralDifference` 运行
- **THEN** hyperlocal_push 的 trajectory_deviation_m SHALL 严格小于
  global_distraction 的（差值 > 0）


### Requirement: 不改已归档 capability 的 spec

本 change 的实施 SHALL NOT 修改任何 `openspec/specs/` 下已有 spec 的
requirement 或 scenario（orchestrator / memory / agent / policy-hack /
multi-day-run / metrics / attention-channel 全部不动）。所有改动限于：
- 新增 `tools/suite_stub_llm.py`
- 修改 `tools/run_variant_suite.py`
- 新增 `tests/test_suite_stub_llm.py` 与 `tests/test_suite_wiring.py`
- 新增 `docs/agent_system/17-suite-wiring.md`
- 更新 `README.md` Development Status

#### Scenario: 已归档 spec 文件未变
- **WHEN** 归档 suite-wiring change 后 `git diff openspec/specs/` 于
  `orchestrator` / `memory` / `agent` / `policy-hack` / `multi-day-run` /
  `metrics` / `attention-channel` 子目录
- **THEN** 输出 SHALL 为空（无修改）
