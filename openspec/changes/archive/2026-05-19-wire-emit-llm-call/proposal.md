## Why

2026-05-20 全量项目扫发现 `emit_llm_call` 在 `instrumentation.py` 定义
但 **0 个 call site** — 永远不被调用。`seed_<N>.llm.jsonl` 永远是空文件。

后果：所有"复现性 lock"对 LLM 维度的承诺 (每次 call 的 tier / latency /
status / retry) 全部空白。答辩问"DeepSeek 失败率多少 / 平均延迟多少 /
fallback 占比多少" — 答不上来。

这是 `comprehensive-runtime-instrumentation` (commit 8fedc2d) 的 task
G13 标记完成但实际没 wire 的同一类 bug — spec'd but not wired。

## What Changes

- 每个 tier client (`_StubTierClient` / `_GeminiTierClient` /
  `_DeepSeekTierClient` / `_AnthropicTierClient` / Volces 复用
  DeepSeek class) 的 `generate()` 方法 SHALL 包装：
  - 测 latency_ms (`time.perf_counter()`)
  - 成功返回前 emit_llm_call(status="success", tier, provider, model,
    latency_ms, attempt=0, max_attempts, key_id)
  - 异常前 emit_llm_call(status="exhausted", exc_class=...)
- `do_something.py` handler 的 except 路径 SHALL emit_llm_call(
  status="fallback") 反映 caller-level fallback decision（区别于
  tier client 内 retry exhaustion）
- 每个 tier client 加 `self._provider` 属性（构造时传入）让 emit
  能拿到 provider 名
- 加 `tier`（sonnet/haiku/nano）参数路径

不改 `_run_with_retry` 行为；不改 emit_llm_call API；不动 LLM_SAMPLE_RATE
sampling 逻辑（已经实现 1% sample + error 100% record）。

## Capabilities

### Modified Capabilities

- `runtime-instrumentation`: emit_llm_call SHALL be wired into all
  tier clients (`generate()` method) — currently spec'd but not wired.

## Impact

**Affected code**:
- `tools/tier_llm_factory.py` (4 tier client `generate` methods, plus
  Volces variant)
- `synthetic_socio_wind_tunnel/agent/operations/handlers/do_something.py`
  (fallback emit)
- `tier_clients` construction sites in `tools/run_variant_suite.py`
  to pass provider name through

**Affected behavior (positive)**:
- `seed_<N>.llm.jsonl` 有真实数据（每个 cell 估 ~6MB at default 1% sample）
- post-mortem 可看 LLM 调用 latency / fallback rate / retry 分布
- 五幕报告 "复现性记录" 段可以引用真实 LLM 使用统计

**Affected behavior (negative)**:
- 每次 LLM call 多 1 个 emit + 1% chance 写 jsonl line. <1ms overhead.

**Test impact**: 1 subprocess e2e test 真跑 dev smoke + 读 llm.jsonl
验证有内容（**这次绝不只测 API 契约**）。
