## Context

prior fix-variant-measurement-and-friction 修了 7 个 bug 后，2026-05-10 的全量 audit 发现 3 个新 bug。本 change 把它们一并修。

**B9（blocker）**：`_detect_encounters(traces)` 只看本 tick 移动过的 agent。证据 `synthetic_socio_wind_tunnel/orchestrator/service.py:481`：

```python
for agent_id, trace in traces.items():
    for loc in trace.locations:
        location_visitors[loc].add(agent_id)
```

`traces` 由 `_dispatch_move` 的成功 sub-step 填充；`WaitIntent` / `ExamineIntent` / `PickupIntent` 在 `_dispatch` 里返回 `(result, None)` —— 不进 traces。后果：agent A 在 cafe dwell 12 tick，agent B 走过 cafe → 抵达 tick 上 location_visitors[cafe] 里只有 B，无 encounter。dwell 期 0 encounter。

**B10（major）**：`compute_reproducibility_lock(provider=None)` 在 `tools/run_variant_suite.py:793`，`aitown_provider` 参数已在 `_run_one_variant` 作用域里但从未传过去。

**B6（major）**：`tools/tier_llm_factory.py::_GeminiTierClient.generate` 不读 `response.usage_metadata`，token count 不进 OperationResult。`metrics/factory.py::_aitown_op_pool_stats` 期望从 `result.prompt_tokens + result.completion_tokens` 算 cost，Gemini 下两个字段都 None → cost = 0。

约束：
- 不破坏 `EncounterCandidate` 现有合同（memory/social_graph/conversation 都消费它）
- determinism Requirement 仍要满足：相同 seed 同样 input 必须产同样 candidate sequence
- 测试 1161 → 至少 1161 不退（理想 +5..10 新测试）

## Goals / Non-Goals

**Goals:**

1. B9 修复：encounter 检测把 stationary co-located agent 算进去。算法切换为"end-of-tick 同 location 的所有 agent 两两配对"。pair 去重保持 (a,b) 字典序、shared_locations sorted。
2. B10 修复：rep_lock 增加 `provider` 字段；`model_version` 改成反映实际 provider 的 hash 或人读字符串。
3. B6 修复：Gemini client `generate` 改成读 `response.usage_metadata.prompt_token_count` / `candidates_token_count`；返回值携带 token 数（通过 OperationResult 流入 cost_breakdown）。
4. 1 seed × 3 day × 20 agent smoke 验证：hp encounter total 不再 < baseline；Gemini provider 下 cost_breakdown.total > 0；rep_lock.provider == "gemini"（or 配置项）。

**Non-Goals:**

- 不重写 `_dispatch` 或 `_dispatch_move` 的 trace 装配——traces 仍由 MoveIntent 生成，只是 _detect_encounters 不再唯一依赖它。
- 不改 `EncounterCandidate` 字段结构。
- 不重跑 30 seed publishable suite。
- 不修 5 个 spec lint failure。
- 不改 OperationResult 的 schema（`prompt_tokens` / `completion_tokens` 字段已存在；只是 Gemini 没填）。

## Decisions

### Decision 1：B9 encounter 检测算法升级 — trace 与 ledger snapshot 合并

**Why**：直接拓展 `_detect_encounters` 是最小侵入修法。从 ledger 拿"本 tick 末每 agent 的 current_location"，把所有 agent（不论是否移动）都加进 `location_visitors`。然后既有的 pair-shared-location 聚合算法不变。

**How**（伪码）：
```python
def _detect_encounters(self, tick_index, traces):
    location_visitors: dict[str, set[str]] = defaultdict(set)
    # (a) trace-based: 走过的 agent 每个 sub-step location 都算
    for agent_id, trace in traces.items():
        for loc in trace.locations:
            location_visitors[loc].add(agent_id)
    # (b) end-of-tick co-presence: ledger snapshot 包括 stationary agent
    for ent in self._ledger.list_entities():
        if ent.location_id:
            location_visitors[ent.location_id].add(ent.entity_id)
    # 后续 pair-shared 聚合算法不变
    ...
```

**关键注意**：
- (b) 加进来后，stationary agent 仅出现在他们的 final location，不进 transit 段；trace-based (a) 仍负责 walking 路径上的 encounter。两者互补不重复（同一 (location, agent) 多次 .add 被 set 自动 dedup）。
- determinism：ledger.list_entities() 必须返回稳定顺序；如果是 dict.values() 则 Python 3.7+ insertion-order 保留 → 已稳定。如果不稳定，外加 sorted。
- 性能：N agents × 1 location each → O(N) 额外开销；总复杂度仍 O(total_trace_length + N)，可忽略。

**备选**：在 `_dispatch` 里给所有 intent 都返回 trace（含 stationary 的 single-location trace）。否决：会让 trace 语义变得不一致——trace 是"运动轨迹"还是"co-presence 标记"？引发其它消费 trace 的代码歧义。Decision 1 路径更干净。

**风险**：[Risk] 现有测试可能假定 stationary agent 不产 encounter → Mitigation：grep `WaitIntent` / "stationary" / "encounter" 跨 tests/，逐一 review；预期 0~3 处需要 update。

### Decision 2：B10 rep_lock provider plumb-through

**Why**：参数 `aitown_provider` 已在 `_run_one_variant(...)` 签名里，只缺一行 plumb-through。

**How**：
```python
rep_lock = compute_reproducibility_lock(
    seed_pool=[seed],
    use_real_llm=use_real_llm,
    variant_names=[variant_name],
    phase_config=_parse_phase_days_to_dict(phase_days),
    provider=aitown_provider if use_aitown else (
        "anthropic" if use_real_llm else "stub"
    ),
)
```

`compute_reproducibility_lock` 已接受 `provider` 参数；只是 caller 没传。检查 reproducibility.py 的 `model_version` 计算逻辑里是否用到 provider：如果 provider 不影响 model_version，需要补，让 model_version 反映 provider（如 `gemini:flash-preview` / `anthropic:haiku-4-5` / `stub:v1`）。

**备选**：把 provider 单独写为 metadata 字段，不混进 model_version。否决：cleaner 的 metadata 是 lock 的一部分；现有 reader 已读 `model_version`，让它反映 provider 比新增字段对 reader 影响更小。

**风险**：[Risk] 老 seed_*.json 的 model_version 是 `stub:v1`，新 run 是 `gemini:flash-preview` → cross-run 比对时 reader 误以为不同 → Mitigation：rep_lock 本来就要"区分实质上不同的 run"，这个变化是预期行为，不是兼容性问题。

### Decision 3：B6 Gemini token 记录

**Why**：`google.genai.GenerateContentResponse` 有 `usage_metadata` 字段（`prompt_token_count`, `candidates_token_count`）。

**How**：把 `_GeminiTierClient.generate` 的返回值从 `str` 改为 `tuple[str, int, int]` —— breaking change，需要更新 caller。或者更稳：让 client 把 token count 缓存在 `self._last_usage` 然后由 OperationPool 读。

更干净的方案：让 `LLMClient` 协议增加可选 `last_usage()` 接口；OperationPool 在 await client.generate 后调 `last_usage()` 拿 token，写入 OperationResult。

最简方案：直接改 OperationPool 的 `_run_op` —— 在调 `client.generate` 后用 `getattr(client, "_last_usage", None)` 读 cached usage。这样不破坏 LLMClient 协议（保持 duck-typing），只新增可选属性。

选**最简方案**：duck-typed `_last_usage`。stub / anthropic 不实现也无所谓（cost = 0 是 acceptable for stub；anthropic SDK 单独修就好，本 change 不动）。

**备选**：硬改 LLMClient 协议返回 tuple。否决：所有 client / test mock 都要改，scope 蔓延。

**风险**：[Risk] Gemini SDK API 不稳定 → Mitigation：try/except 包裹，失败时 _last_usage = None，OperationPool 兼容。

## Risks / Trade-offs

- **[Risk]** B9 修复后 encounter 数量大幅上升（dwell 期 co-presence 现在被算）；之前的 baseline 数值不再可比 → Mitigation：在 docs/audit/ 追加注释，明确"2026-05-10 之后 encounter 口径换了"。30 seed publishable 在新口径下重跑。
- **[Trade-off]** Decision 3 用 duck-typed 属性绕过 LLMClient 协议升级 —— 保留协议简洁，但隐藏了 contract（"实现 _last_usage 才能记 cost"）。可接受，因为 cost 是 observability 不是核心契约；下个 cost-budget change 可能正式化协议。
- **[Risk]** memory/process_tick 在 encounter 派生 events 时按 EncounterCandidate 列表两两生成 → encounter 数翻倍可能导致 memory 内存膨胀（per-tick events 多了）→ Mitigation：观察 1 seed smoke 的 reflection_count / memory size；如显著膨胀再考虑 dedup at memory 层（不是本 change 责任）。

## Migration Plan

1. 改 spec deltas（orchestrator + suite-wiring）+ 本 design 通过 review。
2. 实施 Decision 2（B10 rep_lock provider）—— 最小、独立、零回归风险。
3. 实施 Decision 3（B6 Gemini token）—— 实现 + 测试。
4. 实施 Decision 1（B9 encounter）—— 含 4 个 contract test；跑 1 seed smoke 看 hp encounter 方向反转情况。
5. 全量 pytest 1161+ 不退；新增测试 +5..10。
6. 走通后 commit + archive。

回滚：每个 Decision 单独 commit；smoke 异常回滚到最近 green。

## Open Questions

1. encounter 现在 per-tick × per-co-present-pair 计数 —— 14 day × 100 agent × 12 dwell-tick 可能产 ~10K encounter/day。memory 派生的 encounter event 是否也按 encounter_count 1:1 生成？答：memory.process_tick 已经会从 candidate list 生成 events；如果 memory_growth 显眼再加 dedup-by-day-pair。
2. social_graph 的 weak_tie_formation_count 与 encounter 是否双倍计数？答：social_graph 用 (pair, day) 去重，应不会 double-count；smoke 验证。
