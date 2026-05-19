## MODIFIED Requirements

### Requirement: RetryPolicy 统一类型与默认参数

`synthetic_socio_wind_tunnel.run_resilience.retry.RetryPolicy` SHALL 是
Pydantic frozen 模型，作为所有 tier LLM client 的统一重试参数源。字段：

- `max_attempts: int = 3`（含首次，故 max_retries = max_attempts - 1）
- `base_backoff_seconds: float = 0.5`
- `max_backoff_seconds: float = 8.0`
- `jitter_ratio: float = 0.2`（实际 sleep ∈ [b·(1-j), b·(1+j)]）
- `retryable_exceptions: tuple[type[BaseException], ...]`（默认含
  `TimeoutError` / `ConnectionError` / `asyncio.TimeoutError`）
- `retryable_exc_class_names: frozenset[str]`（默认含三家 LLM SDK
  + httpx 的网络层异常 class names，详见后述 requirement）
- `retryable_http_statuses: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)`
- `fatal_http_statuses: tuple[int, ...] = (400, 401, 403, 404, 422)`

`RetryPolicy` SHALL 提供方法 `next_backoff(attempt_idx: int) -> float`，返回
指数退避 + jitter 后的下一次 sleep 秒数，且永不超过 `max_backoff_seconds`。

`RetryPolicy` SHALL 提供方法 `classify(exc: BaseException) ->
Literal["retryable", "fatal", "unknown"]`，按以下优先级归类：

1. fatal HTTP status (来自 `_extract_status_code(exc)` 提取) → `fatal`
2. retryable HTTP status → `retryable`
3. **`type(exc).__name__ in retryable_exc_class_names`** → `retryable`
   (duck-typed class name match，避免硬依赖三家 SDK)
4. `isinstance(exc, retryable_exceptions)` → `retryable`
5. 否则 → `unknown`

status code 提取方式 SHALL 支持 openai SDK `APIStatusError.status_code`、
google-genai `ServerError.code`、httpx `HTTPStatusError.response.status_code`
三种格式。

#### Scenario: 默认参数构造

- **WHEN** `RetryPolicy()` 默认构造
- **THEN** `max_attempts == 3`；`retryable_http_statuses` 至少含 429 / 500 /
  502 / 503 / 504；`fatal_http_statuses` 至少含 400 / 401 / 403 / 404；
  `retryable_exc_class_names` 至少含 `APIConnectionError`、`APITimeoutError`、
  `ConnectError`、`ReadTimeout`、`RemoteProtocolError`

#### Scenario: 指数退避 with jitter

- **WHEN** `policy.next_backoff(0)`、`policy.next_backoff(1)`、
  `policy.next_backoff(5)` 依次调用，base=0.5、jitter=0.2、max=8
- **THEN** 第 0 次 ∈ [0.4, 0.6]；第 1 次 ∈ [0.8, 1.2]；第 5 次 == 8.0（已撞顶）

#### Scenario: 异常分类 — retryable

- **WHEN** `policy.classify(ConnectionError("..."))` 调用
- **THEN** 返回 `"retryable"`

#### Scenario: 异常分类 — fatal 4xx 立即停

- **WHEN** 构造一个带 `status_code=401` 的 mock APIStatusError，调
  `policy.classify(exc)`
- **THEN** 返回 `"fatal"`；调用方 SHALL NOT 重试

#### Scenario: 异常分类 — openai.APIConnectionError 走 class name 路径

- **WHEN** `policy.classify(exc)` 调用，`exc` 是真实的
  `openai.APIConnectionError(request=None)` 实例（不继承 Python builtin
  `ConnectionError`，无 status_code 属性）
- **THEN** 返回 `"retryable"`（class name "APIConnectionError" 命中默认
  `retryable_exc_class_names` frozenset）

#### Scenario: 异常分类 — httpx.ConnectError 走 class name 路径

- **WHEN** `policy.classify(exc)` 调用，`exc` 是真实的
  `httpx.ConnectError("simulated")` 实例
- **THEN** 返回 `"retryable"`

#### Scenario: 异常分类 — fatal HTTP status 优先于 class name 命中

- **WHEN** 构造一个 class name 为 `"APIConnectionError"` 但又带
  `status_code=401` 的 mock 异常，调 `policy.classify(exc)`
- **THEN** 返回 `"fatal"`（HTTP fatal status 优先级最高，class name 不
  覆盖）

#### Scenario: 异常分类 — 未知 class name 不被误判

- **WHEN** `policy.classify(RuntimeError("random"))` 调用（class name
  `"RuntimeError"` 不在 retryable set，不继承 retryable_exceptions
  type tuple）
- **THEN** 返回 `"unknown"`（调用方 SHALL 视为 fatal，不重试）

## ADDED Requirements

### Requirement: 默认 retryable SDK 异常 class names

`RetryPolicy.retryable_exc_class_names` 字段默认值 SHALL 至少包含以下
12 个 class name 字符串，覆盖三家 LLM SDK + 底层 httpx 的网络层瞬时
异常：

- `APIConnectionError` (openai SDK + anthropic SDK)
- `APITimeoutError` (openai SDK + anthropic SDK)
- `ConnectError` (httpx)
- `ReadError` (httpx)
- `WriteError` (httpx)
- `ConnectTimeout` (httpx)
- `ReadTimeout` (httpx)
- `WriteTimeout` (httpx)
- `PoolTimeout` (httpx)
- `RemoteProtocolError` (httpx — TLS 中途断 / chunked transfer 中断)
- `DeadlineExceeded` (google-genai)
- `ServiceUnavailable` (google-genai)

匹配方式 SHALL 使用 `type(exc).__name__ in retryable_exc_class_names`
精确字符串相等比较，避免：(a) 硬依赖任一 SDK 的 import（stub provider
用户不需要这些 SDK）；(b) `exc.__module__` 路径变化（SDK 升级会重组
模块）。

#### Scenario: 三家 SDK 的 APIConnectionError 都被识别

- **WHEN** 三个 mock 异常 class，名字分别是 `APIConnectionError`、
  `APIConnectionError`、`APIConnectionError`（模拟 openai / anthropic /
  其它 wrapper），依次传给 `classify()`
- **THEN** 三次都返回 `"retryable"`

#### Scenario: httpx 协议中断被识别

- **WHEN** `policy.classify(httpx.RemoteProtocolError("Server disconnected
  before sending response"))` 调用
- **THEN** 返回 `"retryable"`

### Requirement: env override 追加自定义 class names

`RetryPolicy.from_env()` SHALL 支持环境变量
`RESILIENCE_RETRY_EXC_CLASS_NAMES`：逗号分隔的 class name 列表。
解析行为 SHALL 是**追加**（union with default frozenset），不是替换。

每个名字 SHALL strip 前后空白；空字符串 SHALL 被忽略；malformed env
（非字符串 / 非逗号分隔）SHALL log warning + 走默认值。

#### Scenario: 追加自定义 class name

- **WHEN** 设置 `RESILIENCE_RETRY_EXC_CLASS_NAMES=MyCustomError,AnotherErr`
  并调 `RetryPolicy.from_env()`
- **THEN** 返回的 policy 的 `retryable_exc_class_names` 同时包含原 12
  个默认 class name **和** `"MyCustomError"`、`"AnotherErr"`；
  `classify(MyCustomError())` 返回 `"retryable"`；
  `classify(APIConnectionError())` 仍返回 `"retryable"`

#### Scenario: env 为空时使用默认值

- **WHEN** 不设置 `RESILIENCE_RETRY_EXC_CLASS_NAMES` 或设为 `""`
- **THEN** `RetryPolicy.from_env()` 返回 policy 的
  `retryable_exc_class_names` 等于默认 frozenset（恰好 12 元素）

### Requirement: _run_with_retry 必须重试 SDK 网络层异常

`tools.tier_llm_factory._run_with_retry` SHALL 对 `classify` 返回
`"retryable"` 的异常按 `max_attempts` 序列退避 + 重试；包括但不限于
class-name 路径识别的 `APIConnectionError` / `httpx.ConnectError` 等。

`_run_with_retry` SHALL NOT 因为某个 SDK 异常"看起来像 connection
error"就 burn 一个 key cooldown 槽位——必须先走完 `max_attempts`，
最后一次失败才调 `breaker.record_failure()`。

#### Scenario: 2 次 APIConnectionError + 1 次 success

- **WHEN** mock operation 在第 1 / 第 2 次抛 `openai.APIConnectionError`，
  第 3 次返回 success，policy `max_attempts=3`
- **THEN** `_run_with_retry` 返回 success；`breaker.record_success()`
  被调用 1 次；`breaker.record_failure()` 未被调用；
  `policy.next_backoff(0)` + `policy.next_backoff(1)` 两次 sleep
  发生（共 ~1.5s 含 jitter）

#### Scenario: 3 次 APIConnectionError 全失败后 record_failure

- **WHEN** mock operation 三次都抛 `openai.APIConnectionError`，policy
  `max_attempts=3`
- **THEN** 最后一次失败后 `_run_with_retry` 重新 raise 最后那个异常；
  `breaker.record_failure()` 被调用恰好 1 次（不是 3 次）；
  `breaker.record_success()` 未被调用
