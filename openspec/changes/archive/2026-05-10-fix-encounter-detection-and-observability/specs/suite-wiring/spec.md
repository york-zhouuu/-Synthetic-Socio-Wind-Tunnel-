## MODIFIED Requirements

### Requirement: Replan 计数写入 RunMetrics.extensions

每个 seed 的 RunMetrics SHALL 通过 `with_extensions` 携带以下键：

- `replan_count: int`（**plan 真改的 replan 次数**——`new_future_steps` 非空且与原 plan 不全等）
- `replan_no_op_count: int`（**调用了 LLM 但 plan 未变**：fallback 到 deep_copy(unchanged) 的次数）
- `replan_by_day: list[int]`（per-day `replan_count` 计数，长度 == num_days；不含 no_op）
- `replan_no_op_by_day: list[int]`（per-day no-op 计数）
- `reproducibility_lock: dict`（7 字段复现锁；含 `provider` 反映实际跑的 LLM provider）

**语义变更**（fix-variant-measurement-and-friction + fix-encounter-detection-and-observability）：
原 `replan_count` 包含 fallback 的空 replan，让 reader 误以为 plan 被改了
（参见 `docs/audit/2026-05-09-bug-hunt.md` B7）。修订后 `replan_count` 严格表示"plan 真改"。
原 `reproducibility_lock` 调用方硬编码 `provider=None`，让 model_version 永远
是 `stub:v1`（B10）。修订后 `provider` 反映实际 provider（gemini / anthropic / stub）。

实现要点：`Planner.replan` SHALL 返回 `tuple[DailyPlan, bool]` —— 第二个元素 `changed: bool`
表示 plan 是否被真改；`memory.process_tick` 据 `changed` 分流计入 `replan_count` /
`replan_no_op_count`。`compute_reproducibility_lock` SHALL 接收 `provider` 参数：
- `--use-aitown` 启用时，传 `aitown_provider`（即 `--aitown-provider` flag 的值）
- 仅 `--use-real-llm` 启用时，传 `"anthropic"`
- 否则传 `"stub"`

`reproducibility_lock["model_version"]` SHALL 反映 provider，例如：
- gemini provider → `"gemini:flash-preview"`
- anthropic provider → `"anthropic:haiku-4-5"`
- stub → `"stub:v1"`（保留兼容老快照的字符串）

不得新增 RunMetrics 的 typed 字段（metrics spec 明文 extensions 作未来挂载点）。

#### Scenario: replan_count 不再含空 replan
- **WHEN** 一个 14 day run，gd variant + StubReplanLLM(预修订时返回空 plan)
- **THEN** `extensions["replan_count"]` SHALL 为该跑里 plan 真被改的次数；
  `extensions["replan_no_op_count"]` SHALL 累计所有 fallback 次数

#### Scenario: replan_count 等于 by_day 之和
- **WHEN** 一个 14 day run 的 RunMetrics dump
- **THEN** `extensions["replan_count"] == sum(extensions["replan_by_day"])`；
  `extensions["replan_no_op_count"] == sum(extensions["replan_no_op_by_day"])`

#### Scenario: Dump 到 seed_<N>.json
- **WHEN** `run_variant_suite.py` 跑完一个 seed
- **THEN** `seed_<N>.json` 中 `run_metrics.extensions` SHALL 含 `replan_count`、
  `replan_no_op_count`、`replan_by_day`、`replan_no_op_by_day`、
  `reproducibility_lock` 五键

#### Scenario: rep_lock provider 反映 gemini 配置
- **WHEN** `--use-aitown --aitown-provider gemini` 跑 1 seed
- **THEN** `extensions["reproducibility_lock"]["provider"]` SHALL == `"gemini"`；
  `extensions["reproducibility_lock"]["model_version"]` SHALL 包含 `"gemini"`
  子串（不再是 `stub:v1`）

#### Scenario: rep_lock provider 反映 stub 配置
- **WHEN** 不带 `--use-aitown` 也不带 `--use-real-llm` 跑 1 seed
- **THEN** `extensions["reproducibility_lock"]["provider"]` SHALL == `"stub"`
