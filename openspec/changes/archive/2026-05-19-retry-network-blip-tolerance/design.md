## Context

`RetryPolicy` (`synthetic_socio_wind_tunnel/run_resilience/retry.py`)
是 D1' 事故 (2026-05-15) 后引入的跨 provider 统一重试策略。三家 tier
client (`_GeminiTierClient` / `_DeepSeekTierClient` /
`_AnthropicTierClient`) 都在 `tools/tier_llm_factory.py` 内部通过
`_run_with_retry()` 调用，policy 共享同一实例。

`classify()` 的判定优先级：
1. `_extract_status_code(exc)` → HTTP status code → fatal / retryable
2. `isinstance(exc, self.retryable_exceptions)` → retryable
3. 否则 `"unknown"` → `_run_with_retry` 视为 fatal，立即 raise

现状漏洞：openai / anthropic / httpx 的网络层异常**既没有 HTTP status
code**（它们正是"还没拿到响应"的标志），**又不继承** Python builtin
`ConnectionError` / `TimeoutError`（这两个是 `OSError` 子类）。所以
`classify()` 走到第 3 步，所有 SDK 级网络错误被错判 unknown，跳过 retry。

任何 transient 网络层失败都会触发这类异常 —— 包括但不限于：
self-DDoS 引起的 server-side silent TCP drop（D2 attempt 6 真因，独立
由 `stagger-worker-spawn` 修复）、跨境路由瞬时抖动、本机 DNS / TLS
握手偶发失败、SDK 内部 socket pool 边界。本 change 不区分来源——
只确保任何一次抖动**都不应该**立刻 burn 1 个 key cooldown 槽位。

## Goals / Non-Goals

**Goals:**
- `openai.APIConnectionError` / `httpx.ConnectError` / 同族异常进入
  retryable 路径，让 `_run_with_retry` 完整跑完 `max_attempts=3` 的
  backoff 序列再决定是否真的 burn key
- 实现路径不引入硬依赖（duck-typed by class name），三家 SDK 任一未
  安装都不影响 retry policy import + behavior
- 既有 `(TimeoutError, ConnectionError, asyncio.TimeoutError)` Python
  builtin 路径保持向后兼容；既有 HTTP status 判定路径不动
- 用户可通过 env 追加自定义 class name（不替换默认）

**Non-Goals:**
- 不引入 SDK 硬依赖
- 不改 `_run_with_retry` 主循环
- 不改 circuit breaker per-key cooldown 时长 / `LLMHealthTracker`
  阈值 / HTTP fatal status set
- 不识别 SDK 内部的 sub-exception（如 `openai.RateLimitError` —— 那
  个已经走 HTTP 429 status code 路径）
- 不修复 `do_something.py` 的 `__cause__` chain logging
- 不解决 SDK 不一致的 timeout 语义（用户层 timeout 已被
  `read_timeout=300.0` 配置统一）

## Decisions

### D1: Duck-typed by class name, not isinstance

**选项**:
- (A) 用 `type(exc).__name__ in frozenset` 字符串匹配
- (B) `try: import openai; except: ...` 然后 `isinstance(exc,
  openai.APIConnectionError)` —— 加 SDK 硬依赖
- (C) 检查 `exc.__module__` startswith `"openai."` / `"httpx"` 等

**选定: A — class name 字符串匹配**

理由：
- (B) 强行引入三家 SDK 作为运行时依赖，但 stub provider 用户不需要这些
  SDK；而且 import-time 错误会让整个 retry.py 不可用
- (C) module 路径不稳定（openai SDK 内部重组过几次）；且 httpx 异常
  在三家 SDK 内部 re-raise 时可能丢失原 module 信息
- (A) 三家 SDK 都遵循惯例命名（`APIConnectionError` / `APITimeoutError`
  / `ConnectError`），class name 是稳定 contract。即使 SDK 升级换模块
  路径，只要 class 名不改就继续生效。
- 缺点：理论上 user code 可能定义同名 class 但语义不同 —— 在我们的
  场景里这是 LLM client 内部，控制权在 retry.py 内，不存在外部命名冲突
  风险。

### D2: 加新字段，不改现有 `retryable_exceptions` 字段

**选定: 新字段 `retryable_exc_class_names: frozenset[str]`**

理由：
- 现有 `retryable_exceptions: tuple[type[BaseException], ...]` 字段
  签名是"type tuple"，强行塞 string 会破坏 type contract
- 新字段语义清晰：name-based vs type-based
- `frozenset` 比 tuple 查找快（hash O(1) vs linear scan）；且 frozenset
  unhashable item 在 Pydantic frozen model 上更自然

### D3: env override 是"追加"而不是"替换"

**选定: 追加语义**

理由：
- 替换语义太脆弱（用户少写一个就失去关键覆盖）
- 追加语义安全：默认 11 个常见 SDK class 始终有保护，env 只是开口子让
  用户加项目特异的（比如他们自家 SDK wrapper 的命名）
- env 名 `RESILIENCE_RETRY_EXC_CLASS_NAMES`，逗号分隔

### D4: classify 优先级 — class name 检查放在 isinstance 检查**之前**

理由：
- class name set 是 O(1) hash lookup；isinstance loop 是 O(N) where
  N=len(retryable_exceptions)
- 大部分实际 retry 来自 SDK 异常，命中 class name 更频繁
- 把热点放前面省 cycle

但 HTTP status code 检查仍最优先 —— 如果 server 已经返回 401/403 等
fatal status，即使被包成 `APIConnectionError`，也应该走 fatal 路径
（避免重试无意义请求）。

### D5: 默认 class name 集合 (11 个)

```
"APIConnectionError",       # openai + anthropic (same name)
"APITimeoutError",          # openai + anthropic
"ConnectError",             # httpx
"ReadError",                # httpx
"WriteError",               # httpx
"ConnectTimeout",           # httpx
"ReadTimeout",              # httpx
"WriteTimeout",             # httpx
"PoolTimeout",              # httpx
"RemoteProtocolError",      # httpx (TLS 中途断)
"DeadlineExceeded",         # google-genai
"ServiceUnavailable",       # google-genai
```

12 个其实——`google-genai` 那两个 future-proof（项目当前用 deepseek
+ volces + anthropic，但 fallback 链里 Gemini 仍是 active 选项）。

### D6: 不动 `_extract_status_code` 函数

理由：
- 它的 duck-typed status code 提取已经覆盖三家 SDK 的常见路径
- 真要扩展（比如读 `exc.body.error.code`）属于独立改进，不在本 change
  scope

## Risks / Trade-offs

**[R1] User-defined exception 命名冲突误判 retryable**
→ Mitigation: retry.py 是 internal infra 模块，用户层异常不会经过
  `classify()`。即便误判，retry 3 次后仍会 raise；blast radius 是
  "3× backoff delay"，非数据破坏。可接受。

**[R2] SDK 升级改 class name**
→ Mitigation: SDK class name 是稳定 contract（openai/anthropic 历史
  从未改过 `APIConnectionError`）；如果某天改了，hypothesis property
  test 会在升级后 CI 抓到（class name 不命中 → unknown → 测试断言
  retryable 失败）。

**[R3] 重试时间放大 user-facing latency**
→ Mitigation: max_attempts=3, backoff 0.5/1.0/2.0s + jitter，最坏
  total ~3.5s。do_something 单次调用本来就是 30-60s 级别（DeepSeek
  v4-pro），多 3.5s 是 ~6%。可接受。

**[R4] 命中 retryable 但 SDK 内部状态损坏（rare）**
→ Mitigation: `_run_with_retry` 每次 attempt 都重新 `await operation()`
  即重新走 SDK 调用链，client 状态在 SDK 层自我恢复（httpx client
  pool 会重建 connection）。已有现实数据支持（D1' fix 已落地一周 +
  这次扩展 surface）。

**[R5] hypothesis 测试发现意外 class name 也被命中**
→ Mitigation: property test 用 ASCII 随机字符串（如 `"FooBar"`
  类型 random class），统计上不会命中 12-element frozenset。

## Migration Plan

1. 部署：纯 in-process Python 改动，无 DB / 配置文件 / 长连接 state
   迁移；新代码生效需 worker restart
2. 验证：先在 dev smoke 验证 retry 路径触发（mock 抛 APIConnectionError
   2 次后成功 → 断言 `attempt + 1 == 3 + success` 序列）
3. publishable 灰度：下一次 publishable run 起即生效；通过 log line
   `[retry] attempt 1/3 failed: APIConnectionError; backing off 0.5s`
   监控
4. Rollback：如果某种异常被误判 retryable 导致问题，env 设
   `RESILIENCE_RETRY_DISABLE_CLASS_NAMES=1` 立刻关闭新路径（保留现有
   isinstance 行为）—— 这个 fallback flag 在 tasks 中列出

## Open Questions

- (闭合) 是否需要给 Gemini 加 google-genai 的具体异常？答：D5 已加
  `DeadlineExceeded` + `ServiceUnavailable`。
- (闭合) env override 替换 vs 追加？答：D3 选追加。
- (闭合) 改不改 `_run_with_retry` 主循环？答：D 不改。
