## Why

**这是一个 defense-in-depth bug fix，不是 D2 attempt 6 事故的根因
修复**——D2 那次事故的真根因经 2026-05-19 22:30+ 的二次 log 取证
是 **multi-worker 同时 spawn 触发 self-DDoS**，独立修复见
`stagger-worker-spawn` change。但 retry 路径里仍然存在一个独立 bug
**让 self-DDoS 的影响被放大** —— 修了它能让任何 transient SDK 网络
异常少烧 1 张 key cooldown，单独有价值。

精确 bug（实测验证）：

- `tools/tier_llm_factory.py:273::_run_with_retry` 完整 retry + 8-key
  circuit breaker 都在
- 但 `synthetic_socio_wind_tunnel/run_resilience/retry.py::
  RetryPolicy._default_retryable_excs()` 只列了 Python builtins
  `(TimeoutError, ConnectionError, asyncio.TimeoutError)`
- 三家 LLM SDK 的网络层异常 (`openai.APIConnectionError` /
  `httpx.ConnectError` / `anthropic.APIConnectionError`) **完全不继承**
  Python builtin `ConnectionError`（那个是 `OSError` 子类）
- 实测：`isinstance(openai.APIConnectionError(request=None),
  ConnectionError) == False`（MRO: `APIConnectionError → APIError →
  OpenAIError → Exception → BaseException`，绕过 OSError）
- → `classify()` 走完所有判定 → 返回 `"unknown"` → `_run_with_retry`
  立刻 raise + record_failure → **零重试**

为什么仍然值得修：

无论 transient 失败来自何处——**self-DDoS 引起的 server-side TCP drop**
（D2 attempt 6 的真因）、**跨境路由瞬时抖动**、**本机 DNS / TLS 握手
偶发失败**、**SDK 内部 socket pool 边界情况**——**都长得一样**：抛
`openai.APIConnectionError`。修了这条 classify bug，single transient
失败不再直接 burn 1 个 key cooldown 槽位，给 8-key pool 增加足够的
弹性区间，让 `stagger-worker-spawn` 的主修复有 fallback safety net。

关键限定：

- 这个 fix 不能修复**持续**的 server-side outage / 网络持续不可达
  ——retry 只能对**间歇性**失败有效
- D2 attempt 6 的真根因是 self-DDoS，主修复必须是降并发（见
  `stagger-worker-spawn`）；retry fix 只是减轻附带伤害
- D2 attempt 6 错误归因到"家里网络"的诊断已撤回（2026-05-19 23:00+
  二次取证后修正）

## What Changes

- `RetryPolicy.classify()` 新增 **duck-typed class-name 匹配路径**：在
  现有 HTTP status / isinstance 判定基础上，加 `type(exc).__name__`
  字符串匹配，识别三家 LLM SDK 的网络层 transient 异常为 `retryable`。
- 新增 `RetryPolicy.retryable_exc_class_names: frozenset[str]` 字段，
  默认 11 个 class name 覆盖 openai / anthropic / httpx / google-genai
  的连接 + 超时 + 协议中断异常。
- `from_env()` 支持 `RESILIENCE_RETRY_EXC_CLASS_NAMES` 环境变量逗号
  分隔追加（不替换）默认集合。
- **NOT** 引入任何硬 import 三家 SDK（duck-typed 是有意设计：stub-
  friendly + 避免 import-time 错误 + 不增加依赖）。
- **NOT** 改 `_run_with_retry` 主循环、circuit breaker cooldown、
  `LLMHealthTracker.FallbackBudgetExceeded` 阈值、HTTP status fatal
  集合。
- **NOT** 修复 `do_something.py:186` 的 `__cause__` chain logging
  （独立诊断改进，留 follow-up）。

## Capabilities

### New Capabilities

（无新 capability。bug fix 性质，扩展现有 retry 行为而非新加能力。）

### Modified Capabilities

- `run-resilience`: `RetryPolicy.classify()` 新增 SDK 网络层异常 (by
  class name) → `retryable` verdict 的判定路径；新增 retryable exc
  class names 字段 + env override。

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/run_resilience/retry.py` — `RetryPolicy`
  加字段 + `classify()` 加判定路径 + `from_env()` 加 env 解析

**Affected behavior (positive)**:
- DeepSeek / Anthropic / Gemini 三家 client 在遇到瞬时网络抖动时自动
  按 backoff retry（默认 3 attempts × 0.5-8s 指数退避），不再一次抖动
  烧掉一个 key cooldown 槽位
- 8-key cooldown 累积速度大幅下降 → `AllKeysOpenError` 触发概率降低
  → `FallbackBudgetExceeded` worker 自杀概率降低 → publishable run
  稳定性提升

**Not affected**:
- 真正的 fatal 错误（401 鉴权 / 402 余额 / 404 not found / 422
  unprocessable）仍走 fatal 路径，**不**被错误地重试
- circuit breaker / health tracker / fallback handler 逻辑全部不动
- stub provider 行为不变

**Dependencies**: 无新依赖；`openai`、`anthropic`、`httpx`、
`google-genai` 仍作为运行时可选依赖。

**Test impact**: 新增 ~17 test（unit + integration + fault injection
+ property + env），既有 1700+ regression 不动。
