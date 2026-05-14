## Why

2026-05-10 的全量 audit（在 fix-variant-measurement-and-friction 完成后）发现 3 个新 bug，其中一个是 **blocker**：

- **B9 (blocker)**：`Orchestrator._detect_encounters` 只看本 tick 移动过的 agent；坐着 dwell 的 agent 完全不进 `location_visitors` → encounter **系统性低估**。hp 把 10 个 agent 拉到同一地点 dwell 是 thesis 的核心信号路径，结果"抵达 tick 一次性记完所有 pair，之后 12+ 个 dwell tick 0 encounter"，而 baseline 的 agent 全天在路上跑、每 tick 都有 encounter。这**直接解释**了之前 14-day suite 的"hp encounter -6.8% 反向"诡异结果——大概率是 measurement artifact，不是 thesis null。
- **B10 (major)**：`tools/run_variant_suite.py:793` 调 `compute_reproducibility_lock` 时硬编码 `provider=None`，`aitown_provider` 在作用域内但从不传进去 → rep_lock.model_version 永远是 `stub:v1`，无法区分 gemini / anthropic / stub run 的复现性 metadata。
- **B6 (major, 旧 audit 延后的)**：`tools/tier_llm_factory.py::_GeminiTierClient.generate` 不记录 prompt/completion tokens → Gemini 路径下 `cost_breakdown.total = 0`，cost 永远归零，违反 cost 监测合同。

不修 B9 → 30 seed publishable run 的 encounter 信号继续被遮；不修 B10 → 复现性 metadata 误导未来的对照分析；不修 B6 → Gemini quota 实际花掉但 invoice 看不到。三个一起修。

## What Changes

- **MODIFIED**：`orchestrator::路径相遇检测`——`_detect_encounters` 增加 stationary agent 路径：从 `Ledger` 当前快照中读所有 agent 的 `current_location`，与 trace-based location_visitors 合并；同 location 上"坐着的 + 经过的"agent 之间也产 EncounterCandidate。pair 去重以 (a,b) 字典序键聚合 shared_locations；不增加 candidate 数量上限。
- **MODIFIED**：`suite-wiring::reproducibility_lock`——run_variant_suite 把 `aitown_provider`（gemini / anthropic / stub）传给 `compute_reproducibility_lock(provider=...)`；rep_lock 的 `model_version` SHALL 反映实际跑的 provider。
- **IMPLEMENTATION ONLY (no spec delta)**：Gemini client 改成记录 token counts，stamp 到 OperationResult.prompt_tokens / completion_tokens，让 `_aitown_op_pool_stats` 能算出真 cost。`metrics/spec.md` 的 cost_breakdown 合同没变。
- **NON-GOAL**：本 change **不**重跑 30 seed publishable run；只跑 1 seed × 4 variant smoke 验证 hp encounter 方向是否反转。
- **NON-GOAL**：本 change **不**改 ai-town port / dialogue / reflection 流程。
- **NON-GOAL**：本 change **不**触碰 5 个 spec lint 失败（perception/map-service/navigation/simulation/collapse）——纯 SHALL/MUST 关键字补丁，留给 lint-cleanup change。

## Capabilities

### New Capabilities
无。

### Modified Capabilities
- `orchestrator`: 路径相遇检测口径从"路径交集"扩到"co-presence at end-of-tick"——包括 stationary agent。
- `suite-wiring`: rep_lock.model_version 反映 provider；新增 `provider` 字段写入 metadata。

## Impact

**代码**：
- `synthetic_socio_wind_tunnel/orchestrator/service.py::_detect_encounters` —— 增加 ledger snapshot 读取 stationary agents，合入 location_visitors
- `tools/run_variant_suite.py::_run_one_variant` —— 把 `aitown_provider` 传到 rep_lock 调用
- `tools/tier_llm_factory.py::_GeminiTierClient` —— 提取 `usage_metadata` 字段映射到 prompt_tokens / completion_tokens；让 OperationPool 收 token 数据
- `synthetic_socio_wind_tunnel/agent/operations/pool.py`（如需）—— 给 OperationResult 写 token 字段（已存在则只确保 Gemini 路径填）

**测试**：
- 新增 `tests/test_encounter_detection_stationary.py`：
  - 1 个 stationary agent + 1 个 walking-through agent → encounter 应被检测到
  - 2 个 stationary agent at same loc → encounter 应被检测到
  - 2 个 stationary agent at different loc → 无 encounter
  - 跨 tick 两 stationary 仍共在 → encounter 每 tick 算一次
- 新增 `tests/test_run_variant_suite_provider_in_rep_lock.py`：构造 1 seed × 1 day run with provider="gemini"，断言 rep_lock["provider"] == "gemini"
- 新增 `tests/test_gemini_client_records_tokens.py`：mock Gemini response with usage_metadata；断言 OperationResult.prompt_tokens > 0

**API / 契约**：
- `EncounterCandidate` 数据结构不变，仅产出条件扩展；下游 reader（memory/social_graph/conversation 的 process_tick）已经按 candidate 列表消费，向前兼容。
- `RunMetrics.extensions.reproducibility_lock` 新增 `provider` 字段（向前兼容 — 现有 reader 只读 `seed_pool` / `model_version` 等，不会因此 break）。

**外部影响**：
- 修复后 hp 的 encounter density 信号大概率从"-6.8% reverse"变为正向；之前 14-day suite output 的 "thesis null" 结论需要重写。
- 30 seed publishable run 推到下个 change（命名建议 `publishable-30-seed-suite`）。
