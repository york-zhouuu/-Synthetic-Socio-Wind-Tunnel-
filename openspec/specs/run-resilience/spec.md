# run-resilience Specification

## Purpose
TBD - created by archiving change run-resilience. Update Purpose after archive.
## Requirements
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

### Requirement: 所有 tier client 共用同一 RetryPolicy

所有 tier client SHALL 共用调用方注入的同一 `RetryPolicy` 实例，由
`tools/tier_llm_factory.build_tier_clients(*, provider, retry_policy=None,
...)` 新增的 `retry_policy: RetryPolicy | None` 参数提供；为 None 时从
环境变量构造默认实例（见"配置热重载"requirement）。

`build_tier_clients` SHALL 把同一 `RetryPolicy` 实例传给所有内部 tier client
构造器（`_GeminiTierClient` / `_DeepSeekTierClient` / `_AnthropicTierClient`）。

每个 tier client 的 `generate(prompt, ...)` 实现 SHALL：

1. 进入循环 `for attempt in range(retry_policy.max_attempts)`
2. 调底层 SDK；捕获异常
3. `retry_policy.classify(exc)` == `"fatal"` → 立即 `raise`
4. `retry_policy.classify(exc)` == `"retryable"` 且 attempt < max-1 →
   `asyncio.sleep(retry_policy.next_backoff(attempt))` 后继续
5. 用尽所有 attempt 后 raise 最后一次的 exception，**SHALL** 附加 `__cause__`
   或 `add_note` 标注 attempt 历史

`_GeminiTierClient` 现有的 `asyncio.wait_for(45s)` + 手写 1-retry SHALL
被替换为 `RetryPolicy` 驱动的循环。

#### Scenario: 3 次 retryable 后第 4 次抛
- **WHEN** mock provider 抛 `ConnectionError` 4 次，policy `max_attempts=3`
- **THEN** `await client.generate(...)` SHALL 在前 3 次失败后抛
  `ConnectionError`；不进行第 4 次 SDK 调用

#### Scenario: 1 次 fatal 立即抛、不重试
- **WHEN** mock provider 抛 401 APIStatusError 1 次
- **THEN** `await client.generate(...)` SHALL 立刻抛；total SDK call count == 1

#### Scenario: 第 2 次 retryable 后成功
- **WHEN** mock provider 第 1 次抛 `TimeoutError`、第 2 次成功
- **THEN** `await client.generate(...)` SHALL 返回成功 response；调用次数 == 2；
  attempt 0 与 attempt 1 之间 sleep 落在 `policy.next_backoff(0)` ± 0.1s

### Requirement: Per-key 熔断器

`PerKeyCircuitBreaker` SHALL 为多 key tier client（DeepSeek / Gemini multi-key
模式）提供 per-key 熔断保护，类位于
`synthetic_socio_wind_tunnel.run_resilience.circuit_breaker`。状态机：
closed → open → half-open → closed/open。

- 连续 `failure_threshold`（默认 5）次失败 → open
- open 状态持续 `cooldown_seconds`（默认 300）后进入 half-open
- half-open 状态下放行 1 次探测；成功 → closed；失败 → open + cooldown 加倍
  （capped at 1800s = 30 min）

`_DeepSeekTierClient` 的 round-robin pick SHALL skip 处于 open 状态的 key；
所有 key 都 open 时 SHALL 抛 `AllKeysOpenError`（含 next-available timestamp）。

#### Scenario: 单 key 连续失败触发熔断
- **WHEN** 单 key DeepSeek client，mock 抛 ConnectionError 5 次
- **THEN** 第 6 次调用 SHALL 不进入 SDK，立即抛 `AllKeysOpenError`

#### Scenario: 多 key 部分熔断仍可服务
- **WHEN** 2-key DeepSeek client，key0 已 open、key1 closed
- **THEN** 后续 `generate` 调用 SHALL 全走 key1；不触发 key0

#### Scenario: half-open 探测成功后恢复
- **WHEN** key0 open 后等过 `cooldown_seconds`，mock 让下一次调用成功
- **THEN** key0 状态 SHALL 回到 closed；该 key 的失败计数 SHALL 清零

### Requirement: HTTP 连接池统一契约（所有 provider）

`tools/tier_llm_factory.py` 的所有 tier client 构造器 SHALL 显式注入自定义
`httpx.AsyncClient`（或 SDK 等价的传输配置），不得依赖 SDK 默认连接池。所有
provider 的连接池 SHALL 使用以下参数：

- `max_connections`：默认 600（覆盖 500 protag + buffer）；可由
  `RESILIENCE_POOL_MAX_CONNECTIONS` 覆盖
- **`max_keepalive_connections`：默认 0**（禁止 socket 复用，断 CLOSE_WAIT
  累积路径）；可由 `RESILIENCE_POOL_MAX_KEEPALIVE` 覆盖
- `connect_timeout`：默认 10s
- `read_timeout`：默认 45s
- `write_timeout`：默认 10s
- `pool_timeout`：默认 30s

`_GeminiTierClient` SHALL 通过 monkey-patch 或官方 `http_options` 路径
（取 SDK 版本支持的方式）注入上述配置；具体路径在实现时基于 `pip show
google-genai` 版本号选择。注入失败时 SHALL fail-fast（raise `RuntimeError`），
不静默退化到 SDK 默认。

#### Scenario: Gemini client 注入 keepalive=0
- **WHEN** 默认构造 `_GeminiTierClient(...)`、读取内部 httpx 实例
- **THEN** `client._limits.max_keepalive_connections` SHALL == 0；
  `max_connections` SHALL == 600

#### Scenario: DeepSeek client 注入 keepalive=0
- **WHEN** 默认构造 `_DeepSeekTierClient(...)`、读取内部 httpx 实例
- **THEN** 每个 round-robin 的 httpx async client 的
  `_limits.max_keepalive_connections` SHALL == 0

#### Scenario: 环境变量覆盖默认
- **WHEN** `RESILIENCE_POOL_MAX_KEEPALIVE=10` 且重启 worker
- **THEN** 新构造的 tier client `max_keepalive_connections` SHALL == 10
  （用于调试场景；publishable 默认 0）

### Requirement: 周期性 client 回收

每个 tier client SHALL 维护一个调用计数 `_call_count`；每达到
`recycle_after_calls`（默认 1000，可由 `RESILIENCE_RECYCLE_AFTER_CALLS` 覆盖）
SHALL 主动调用底层 httpx `aclose()` 并重建一个等价配置的新实例，把
`_call_count` 重置为 0。

回收过程 SHALL 与同时发起的其它 in-flight call 协调：进行回收的 await SHALL
等待已发起 call 全部完成才 close 旧 client。回收失败（aclose 抛异常）SHALL
log warning 但不阻塞后续 call（旧 client 标记 deprecated，新 call 用新 client）。

#### Scenario: 1000 次 call 后回收触发
- **WHEN** 一个 Gemini tier client 完成第 1000 次 `generate` 调用
- **THEN** 在第 1001 次 call 之前 SHALL 触发一次 `aclose() + rebuild`；
  `_call_count` SHALL 重置为 0；新 client 的 limits 与旧 client 等价

#### Scenario: 回收过程不丢 in-flight call
- **WHEN** 第 1000 次回收触发时还有 5 个 in-flight call
- **THEN** 5 个 call SHALL 全部完成；其结果 SHALL 不丢失；之后才执行 close

### Requirement: Gemini multi-key 支持

`_GeminiTierClient.__init__` SHALL 与 `_DeepSeekTierClient` 对齐 multi-key
逻辑：优先读取 `GEMINI_API_KEYS`（逗号分隔），fallback 单 `GEMINI_API_KEY`
（或 `GOOGLE_API_KEY`）。每个 key 各持自己的 `genai.Client` 实例 + 各自的
httpx client + 各自的 PerKeyCircuitBreaker 状态；`generate` 调用 SHALL
round-robin 跨 keys，且 SHALL skip open 状态的 key。

#### Scenario: 双 key Gemini 构造
- **WHEN** `GEMINI_API_KEYS="k1,k2"` 设置，构造 `_GeminiTierClient(...)`
- **THEN** 内部 SHALL 维护 2 个独立 `genai.Client` 实例 + 2 个 httpx async
  client + 2 个独立 circuit breaker state

#### Scenario: 单 key 兼容
- **WHEN** 仅 `GEMINI_API_KEY="k0"` 设置（无 GEMINI_API_KEYS）
- **THEN** `_GeminiTierClient` SHALL 正常构造、内部仅 1 个 client；
  调用行为与未启用 multi-key 前等价

### Requirement: Per-day checkpoint 写盘

`DayCheckpointWriter` SHALL 提供 `write_partial(output_dir, seed, day_index,
run_metrics_partial, ledger_snapshot, memory_dump) -> Path` 方法，原子地
（先写 `.tmp` 文件再 `rename`）落盘 JSON 到
`<output_dir>/seed_{seed}_day{day_index}.partial.json`。类位于
`synthetic_socio_wind_tunnel.run_resilience.checkpoint`。

partial JSON schema SHALL 包含：

- `seed: int`
- `day_index: int`（已完成的最大 day index）
- `simulated_date: str` (ISO 格式)
- `run_metrics: dict`（`RunMetrics.model_dump()` 输出）
- `ledger_snapshot: dict`（entity locations / item states 摘要，不含完整对话历史）
- `memory_dump: dict`（agent_id → 必要 memory state；体积超过 200 MB SHALL
  log warning 但仍写）
- `provider: str`（产生该 partial 的 LLM provider 名）
- `schema_version: str = "1"`
- `created_at: str` (ISO 8601 timestamp)

`DayCheckpointWriter` SHALL 提供 `read_partial(path) -> dict` 方法做反序列化
+ schema_version 校验；不支持的版本号 SHALL raise `IncompatibleCheckpointError`。

`DayCheckpointWriter` SHALL 提供 `cleanup_partials(output_dir, seed)` 方法
（删除该 seed 的所有 `seed_{seed}_day*.partial.json`）；调用方 SHALL 在最终
`seed_{seed}.json` + `aggregate.json` 都落地后调用。

#### Scenario: 原子写盘
- **WHEN** `write_partial(...)` 期间进程被 SIGKILL
- **THEN** 目标路径 SHALL 要么不存在、要么是合法 JSON（绝不出现写到一半的
  破损文件）。`.tmp` 残留文件 SHALL 在下一次 `write_partial` 开始时被清理

#### Scenario: 读 + schema 校验
- **WHEN** `read_partial(path)` 读一个 `schema_version == "1"` 的合法文件
- **THEN** 返回 dict 含 `seed` / `day_index` / `run_metrics` / `ledger_snapshot`
  / `memory_dump` 字段

#### Scenario: 不兼容 schema 抛
- **WHEN** `read_partial(path)` 读一个 `schema_version == "99"` 的文件
- **THEN** SHALL raise `IncompatibleCheckpointError`，含可读的版本号信息

### Requirement: HealthAudit 单次健康检查

`synthetic_socio_wind_tunnel.run_resilience.health.HealthAudit` SHALL 提供
`audit(run_dir: Path, *, now: datetime | None = None) -> HealthAuditReport`
方法，针对一个 in-progress run 目录做单次健康检查：

- 扫描该目录下 worker pid（从 `run.log` 解析 "pid <N>" 或独立 `pids.json`）
- 对每个 pid 检查：
  - process state（`ps -o stat`）—— `U` / `D` 状态 = 危险
  - 最近 log 行的时间戳（对应 worker log file 的 mtime）距 `now` 的秒数
  - CLOSE_WAIT TCP 数（`lsof -i -p <pid>` 或 `netstat`）
  - 进程 RSS 内存
- 报告 SHALL 返回 `HealthAuditReport(per_worker, overall_status)`；
  `overall_status` ∈ {`healthy`, `warning`, `suspected_deadlock`}

阈值（可由 `RESILIENCE_HEALTH_*` 环境变量覆盖）：

- 静默告警阈：30 分钟（log 无新行）
- 静默死锁阈：60 分钟
- CLOSE_WAIT 告警阈：`ulimit -n` × 0.6
- CLOSE_WAIT 死锁阈：`ulimit -n` × 0.9

#### Scenario: 健康 run 返回 healthy
- **WHEN** mock 一个 worker：log 5 min 前刚有新行、process state == "R"、
  CLOSE_WAIT == 30
- **THEN** `audit(...)` 返回的 `overall_status` SHALL == `"healthy"`

#### Scenario: 静默 7 小时 + 高 CLOSE_WAIT 标记 suspected_deadlock
- **WHEN** mock worker log mtime 7 小时前、process state == "U"、
  CLOSE_WAIT == 2200（撞 ulimit 90%）
- **THEN** `audit(...)` 返回的 `overall_status` SHALL == `"suspected_deadlock"`；
  per_worker 报告中该 pid 的 reasons 列表 SHALL 至少包含 "silent_60min"、
  "high_close_wait"、"uninterruptible_state"

### Requirement: `tools/audit_run_health.py` CLI

`tools/audit_run_health.py` SHALL 提供命令行入口，调用 `HealthAudit.audit`
并以 human-readable 格式打印报告。退出码：

- 0：所有 worker `healthy`
- 1：有 `warning` 但无 `suspected_deadlock`
- 2：至少一个 worker `suspected_deadlock`

`--json` flag SHALL 切换为 JSON 输出（用于自动化集成）。

`--watch <interval_seconds>` flag SHALL 让脚本以指定间隔循环监控（用于
launchd / cron 之外的 ad-hoc 监控）。

#### Scenario: 健康 run 退出 0
- **WHEN** `python tools/audit_run_health.py data/experiments/<healthy_run>/`
- **THEN** SHALL 退出码 0；stdout 含每个 worker 的状态行 + overall 总结

#### Scenario: 死锁 run 退出 2
- **WHEN** `python tools/audit_run_health.py data/experiments/<deadlocked_run>/`
- **THEN** SHALL 退出码 2；stdout 含至少一条 "SUSPECTED DEADLOCK" 标识

### Requirement: HotfixSignalHandler graceful-stop 协议

`HotfixSignalHandler` SHALL 提供 `install(runner: MultiDayRunner) -> None`
方法，向当前进程注册 `SIGUSR1` handler。类位于
`synthetic_socio_wind_tunnel.run_resilience.hotfix`。被触发后 handler SHALL：

1. 设置 `runner._graceful_stop_requested = True` flag
2. **不在 signal handler 中做 I/O**（async-signal-safe 约束）

`MultiDayRunner` 主循环 SHALL 在每个 tick 后检查 `_graceful_stop_requested`；
若为 True SHALL：

1. 跑完当前 tick（**不**跑当前剩余 day）
2. 调用 `DayCheckpointWriter.write_partial(...)` 落 partial（即使当前 day
   未完成；partial 内 `day_index = <已完成的最近 day>`）
3. `sys.exit(0)` 优雅退出（exit code 0）

`SIGTERM` / `SIGINT` 行为 SHALL 保持 Python 默认（立刻抛 KeyboardInterrupt），
不被本 handler 覆盖。

#### Scenario: SIGUSR1 触发 partial 写盘后 exit 0
- **WHEN** 一个 14-day run 跑到 day 5 的 tick 100；用 `kill -USR1 <pid>`
- **THEN** 进程 SHALL 跑完当前 tick → 写
  `seed_{seed}_day5.partial.json`（day_index=5，因为 day 6 未完成）→
  exit code 0；MultiDayRunner SHALL NOT 抛 KeyboardInterrupt

#### Scenario: SIGUSR1 双发送只触发一次
- **WHEN** 在 partial 写盘进行中又收到一次 SIGUSR1
- **THEN** 第二次 SHALL 被忽略；不重入 partial 写盘逻辑

### Requirement: 配置热重载（环境变量）

所有运行时可调参数 SHALL 通过环境变量配置，命名以 `RESILIENCE_` 为前缀：

| 环境变量 | 默认 | 影响 |
|---|---|---|
| `RESILIENCE_RETRY_MAX_ATTEMPTS` | 3 | RetryPolicy.max_attempts |
| `RESILIENCE_RETRY_BASE_BACKOFF` | 0.5 | RetryPolicy.base_backoff_seconds |
| `RESILIENCE_RETRY_MAX_BACKOFF` | 8.0 | RetryPolicy.max_backoff_seconds |
| `RESILIENCE_RETRY_JITTER_RATIO` | 0.2 | RetryPolicy.jitter_ratio |
| `RESILIENCE_POOL_MAX_CONNECTIONS` | 600 | httpx Limits.max_connections |
| `RESILIENCE_POOL_MAX_KEEPALIVE` | 0 | httpx Limits.max_keepalive_connections |
| `RESILIENCE_POOL_CONNECT_TIMEOUT` | 10.0 | httpx Timeout.connect |
| `RESILIENCE_POOL_READ_TIMEOUT` | 45.0 | httpx Timeout.read |
| `RESILIENCE_POOL_WRITE_TIMEOUT` | 10.0 | httpx Timeout.write |
| `RESILIENCE_POOL_TIMEOUT` | 30.0 | httpx Timeout.pool |
| `RESILIENCE_RECYCLE_AFTER_CALLS` | 1000 | tier client 回收阈值 |
| `RESILIENCE_CIRCUIT_FAILURE_THRESHOLD` | 5 | PerKeyCircuitBreaker.failure_threshold |
| `RESILIENCE_CIRCUIT_COOLDOWN` | 300 | PerKeyCircuitBreaker.cooldown_seconds |
| `RESILIENCE_HEALTH_SILENT_WARN_SECONDS` | 1800 | HealthAudit 静默告警阈 |
| `RESILIENCE_HEALTH_SILENT_DEADLOCK_SECONDS` | 3600 | HealthAudit 静默死锁阈 |
| `RESILIENCE_HEALTH_CLOSE_WAIT_WARN_RATIO` | 0.6 | HealthAudit CLOSE_WAIT 占 ulimit -n 比例告警阈 |
| `RESILIENCE_HEALTH_CLOSE_WAIT_DEADLOCK_RATIO` | 0.9 | HealthAudit CLOSE_WAIT 死锁阈 |
| `RESILIENCE_DISABLE` | unset | "1" → 跳过所有 run-resilience 路径，回退旧行为 |

环境变量的读取 SHALL 发生在 worker 启动时（`build_tier_clients` /
`MultiDayRunner.__init__` 内）；改环境变量后必须重启 worker 才生效。

#### Scenario: 默认值生效
- **WHEN** 所有 `RESILIENCE_*` 都未设置；构造 RetryPolicy.from_env()
- **THEN** 字段值 SHALL 与本 spec 表中"默认"列一致

#### Scenario: 环境变量覆盖
- **WHEN** `RESILIENCE_RETRY_MAX_ATTEMPTS=5` 设置；构造 RetryPolicy.from_env()
- **THEN** `policy.max_attempts` SHALL == 5

#### Scenario: RESILIENCE_DISABLE=1 旁路
- **WHEN** `RESILIENCE_DISABLE=1` 设置；`build_tier_clients(...)` 调用
- **THEN** 构造出的 tier client SHALL 走旧路径（SDK 默认 httpx，单 retry）；
  stderr SHALL 含 "WARN: RESILIENCE_DISABLE=1, skipping hardening"

### Requirement: Pre-flight 1000-agent × 1d full smoke

`tools/preflight_full_smoke.py` SHALL 提供命令行入口，跑：

- 1000 agent（项目固定参数，不接受 `--agents` 调整）
- 1 simulation day
- 全 4 variant（baseline / hyperlocal_push / global_distraction / phone_friction）
- 1 seed
- 配置 SHALL 与 publishable run 一致（同 provider / 同 num_protagonists 推荐
  500 / 同 tier 路由）

退出码：

- 0：4 variant 全部完成且写出非空 `seed_*.json` 且无 worker 健康警告
- 1：有 variant 失败或 health audit 报告 warning / suspected_deadlock

#### Scenario: 健康 preflight 退出 0
- **WHEN** `python tools/preflight_full_smoke.py --provider deepseek` 在
  健康环境跑完
- **THEN** SHALL 退出码 0；stdout 含 4 个 variant 的 wall time + LLM call
  count + CLOSE_WAIT peak 报告

#### Scenario: 检测到死锁退出 1
- **WHEN** 跑 preflight 期间任一 worker 触发 `suspected_deadlock`
- **THEN** SHALL 退出码 1；stderr 含失败 worker 的诊断行（pid / state /
  silence_duration）

### Requirement: `run_variant_suite.py` 集成 resilience flag

`tools/run_variant_suite.py` SHALL 支持以下 CLI flag：

- `--resume`：默认从最近 `*.partial.json` 接着跑；若该 variant 已有
  `seed_{N}.json` 则 skip（保留已有行为）；若仅有 partial 则从 partial
  的 `day_index + 1` 开始
- `--resume-from-day=N`：显式指定起点 day index（覆盖 `--resume` 自动检测）
- `--skip-preflight`：dev 模式可跳过 preflight gate；publishable 模式
  （`--mode publishable` 或当前事实上的 publishable 参数：`--agents 1000
  --num-days 14`）该 flag SHALL 被忽略并 stderr 打印警告

publishable 模式（agents == 1000 且 num_days == 14）SHALL 默认要求
preflight pass 才进入正式 run；preflight 失败 SHALL 终止 suite 且退出码 != 0。

#### Scenario: --resume 从 partial 接续
- **WHEN** `data/experiments/<run>/variant_baseline/` 有
  `seed_42_day5.partial.json` 但无 `seed_42.json`；调
  `run_variant_suite.py --resume`
- **THEN** baseline / seed=42 的 run SHALL 从 day 6 开始（day 5 已完成）；
  最终落 `seed_42.json` SHALL 包含 day 0-13 的完整数据

#### Scenario: --resume 旧 run 无 partial 降级 + 警告
- **WHEN** 某 variant 目录既无 partial 也无最终 JSON；调 `--resume`
- **THEN** SHALL 从 day 0 开始跑；stderr SHALL 含 "WARN: no partial found,
  resuming from day 0"

#### Scenario: publishable 模式强制 preflight
- **WHEN** `run_variant_suite.py --agents 1000 --num-days 14 --skip-preflight`
- **THEN** suite SHALL 仍执行 `preflight_full_smoke.py` 一次；preflight 失败
  时整 suite 退出码 != 0；stderr SHALL 含 "publishable mode ignores
  --skip-preflight"

### Requirement: 公共 API re-export

`synthetic_socio_wind_tunnel/__init__.py` SHALL re-export 以下 run-resilience
公共类型，使外部代码可直接 `from synthetic_socio_wind_tunnel import RetryPolicy`：

- `RetryPolicy`
- `PerKeyCircuitBreaker`
- `DayCheckpointWriter`
- `HealthAudit`
- `HealthAuditReport`
- `HotfixSignalHandler`

`synthetic_socio_wind_tunnel/run_resilience/__init__.py` SHALL 同步 re-export
上述 + 内部 helper（`AllKeysOpenError` / `IncompatibleCheckpointError`）。

#### Scenario: 顶层 import 成功
- **WHEN** `from synthetic_socio_wind_tunnel import RetryPolicy,
  DayCheckpointWriter, HealthAudit` 执行
- **THEN** import SHALL 成功，无 ImportError / 循环依赖

### Requirement: Fitness-audit 探针翻绿

`synthetic_socio_wind_tunnel/fitness/audits/` SHALL 新增 `run_resilience.py`
audit module，包含 `phase2-gaps.run-resilience` 探针，检查：

- 模块 `synthetic_socio_wind_tunnel.run_resilience` 可 import
- `tools/audit_run_health.py` 存在且可执行
- `tools/preflight_full_smoke.py` 存在且可执行
- `_GeminiTierClient` 与 `_DeepSeekTierClient` 内部 httpx 的
  `max_keepalive_connections == 0`（用 introspection）

`mitigation_change` SHALL == `"run-resilience"`。

#### Scenario: 本 change 实施完成后 audit 翻绿
- **WHEN** 本 change 所有 task 完成后运行 `make fitness-audit`
- **THEN** `phase2-gaps.run-resilience` AuditResult.status SHALL == `pass`

### Requirement: 直接 LLM call 必须 asyncio.wait_for 兜底

项目里所有 LLM call SHALL 走 OperationPool 路径（模式 A，已被
`asyncio.wait_for(handler, timeout=120s)` 包裹）；如果某条调用路径**不能**
走 OperationPool（如 setup 期一次性 LLM call、reflection 内部短路），它
SHALL 自己用 `asyncio.wait_for(llm_client.generate(...), timeout=60s)`
包裹，且 SHALL 有 fallback 路径在 `asyncio.TimeoutError` 时返回安全默认值
（不允许传播为 worker crash）。

适用对象（已知模式 B 调用点）：
- `synthetic_socio_wind_tunnel/memory/reflection.py::reflect`
- `synthetic_socio_wind_tunnel/memory/importance.py::score_importance`
- `synthetic_socio_wind_tunnel/agent/planner.py::Planner.replan`
- `synthetic_socio_wind_tunnel/data_loader/lanecove.py::_generate_life_history_for_one`
- `synthetic_socio_wind_tunnel/data_loader/lanecove.py::_generate_identity_text_for_one`

每个调用点 SHALL 在超时时 log warning 含 `agent_id` / `call_site` /
`elapsed_s`；调用方 SHALL 看到一个语义合理的 fallback 而非异常。

#### Scenario: reflect 超时回退
- **WHEN** mock llm_client.generate 在 `reflect()` 内部 sleep 90s，
  `asyncio.wait_for` timeout 设 60s
- **THEN** `reflect(...)` SHALL 在 60±2s 内返回；返回值 SHALL 是空
  reflection 或 fallback 摘要；SHALL NOT 抛 TimeoutError 给调用方

#### Scenario: importance 超时回退
- **WHEN** mock llm_client.generate 在 `score_importance()` 内部 hang 70s
- **THEN** `score_importance(...)` SHALL 在 60±2s 内返回默认 importance
  分（如 0.5），并 log warning

#### Scenario: lanecove setup 期超时
- **WHEN** `_generate_life_history_for_one` 在 setup_cache MISS 路径，
  mock llm_client.generate hang 80s
- **THEN** SHALL 在 60±2s 内返回 fallback life_history（如空 list 或
  pre-canned generic 模板）；SHALL 不阻塞同批 1000 agent 中的其它 agent

### Requirement: SIGUSR1 在 setup-phase 写哨兵不污染 partial

`MultiDayRunner._write_partial_at_stop()` SHALL 检测 "per_day 为空 ∧ WAL
没写过任何 entry" 这个 setup-phase 状态。在该状态下收到 SIGUSR1
graceful_stop 时：

- SHALL NOT 写任何 `seed_N_day*.partial.json`
- SHALL NOT 修改既有 partial 文件
- SHALL 在 output_dir 下写一个哨兵文件
  `seed_N.aborted_in_setup.json`，包含 `{"seed": N, "aborted_at":
  "<iso datetime>", "reason": "SIGUSR1 received during setup phase",
  "wal_writes": 0, "completed_days": 0}`
- SHALL 让 `result.metadata["graceful_stop"]` == True、
  `result.metadata["aborted_in_setup"]` == True

外部 audit / `tools/resume_publishable.py` SHALL 识别该哨兵文件作为
"该 cell 还没真正启动过，可安全 resume from latest snapshot or fresh"
信号；不应误判为 INTERRUPTED-with-progress。

#### Scenario: setup-phase SIGUSR1 写哨兵
- **WHEN** worker 启动后 5s（还在 setup_cache load、未进入 tick 循环），
  外部发 SIGUSR1
- **THEN** 进程 SHALL 退出码 0；output_dir 下 SHALL 出现
  `seed_<N>.aborted_in_setup.json`；SHALL NOT 出现 `seed_<N>_day*.partial.json`；
  result.metadata SHALL 含 `aborted_in_setup=True`

#### Scenario: 跑了 3 天后 SIGUSR1 不写哨兵
- **WHEN** worker 跑完 day 0-2 写过 3 个 partial 后收到 SIGUSR1
- **THEN** SHALL 走既有 graceful_stop 路径写 `day3.partial.json`（当天进度）；
  SHALL NOT 写 `aborted_in_setup.json`；`result.metadata["aborted_in_setup"]`
  SHALL == False

### Requirement: DialogueService 必须有 rolling cleanup

`DialogueService` SHALL 在每次 `on_day_end` hook（或等价的 day 边界）
evict 满足以下条件的 dialogue（位于
`synthetic_socio_wind_tunnel/conversation/dialogue_service.py`）：

- `dialogue.ended_at_day_index < current_day_index - 2`（**结束于 2 模拟天前**）
- AND `dialogue.status` ∈ {`completed`, `aborted`}（不动 in-progress）

evict 操作 SHALL：
- 保留 `dialogue_id`、`participants`、`ended_at_day_index`、`message_count` 摘要
  到 `_dialogue_summaries: dict[str, DialogueSummary]`
- 释放 `Dialogue.messages: list[DialogueMessage]`、长 prompt 上下文等 detail
- 通过 `to_snapshot_state` 序列化时只序列化 summaries，不带 full messages

`DialogueService` SHALL 暴露 `retrieve_summary(dialogue_id) -> DialogueSummary
| None` 给下游 metric / narrative 用；下游若需 full messages SHALL 改为
通过外部 DialogueArchive 持久化路径（backlog 1.12，暂不实施）。

#### Scenario: day 边界 evict 老对话
- **WHEN** 在 day 5 触发 day_end hook，`_dialogues` 含 4 个 dialogue
  分别结束于 day 1 / day 2 / day 3 / day 4
- **THEN** 结束于 day 1 / day 2 的 dialogue SHALL 被 evict 到
  `_dialogue_summaries`；结束于 day 3 / day 4 的 dialogue SHALL 留在
  `_dialogues`；`retrieve_summary` SHALL 对所有 4 个返回非 None

#### Scenario: in-progress dialogue 不被 evict
- **WHEN** day 10 时 `_dialogues` 里有一个开始于 day 1、status 仍是
  `in_progress` 的 dialogue（异常长对话）
- **THEN** day_end hook SHALL NOT evict 它；它的 messages SHALL 仍可访问

### Requirement: 守护脚本不持有 termination 决策权

所有 daemon / watchdog / LaunchAgent / cron / 自动化运维脚本 SHALL NOT
主动发 SIGUSR1 / SIGTERM / SIGKILL / `launchctl bootout` 任何已存活
进程，**除非**有 explicit `--allow-terminate` flag 且其值是
user-supplied。适用对象包括但不限于 `tools/resume_publishable.py`、
`tools/watchdog_wal_deadlock.py`、`tools/audit_run_health.py`。

允许的 constructive 行为：
- spawn missing workers（idempotent，仅当 PID 不存在时）
- 写 structured event log 给 monitor
- 重启 crashed 服务（系统级 supervisor）

禁止的 termination 行为：
- 自动 SIGUSR1 任何进程
- 自动 SIGKILL 任何进程
- 自动删除 cell 数据
- 自动 unload LaunchAgent / disable cron

human via monitor SHALL 是 termination 唯一决策方。

#### Scenario: resume_publishable 看到 RUNNING_STALE 不发 SIGUSR1
- **WHEN** `tools/resume_publishable.py` 巡检发现某 cell 处于
  RUNNING_STALE 状态（pid 存活 + wal_age > stale_secs）
- **THEN** SHALL 在 log 写 warning 含完整诊断信息；SHALL NOT 调
  `os.kill(pid, signal.SIGUSR1)`；entry["action"] SHALL == "report_only"

#### Scenario: spawn-on-missing 仍然允许
- **WHEN** `tools/resume_publishable.py` 巡检发现某 cell 处于
  INTERRUPTED 状态（pid is None + 有 snapshot）
- **THEN** SHALL spawn 一个 fresh resume worker（constructive recovery，
  不违反不变量）；entry["action"] SHALL == "spawn_resume"

### Requirement: graceful_stop 不写假 seed_N.json 不删 partials

`tools/run_variant_suite.py` 在 per-seed 主循环里 SHALL 检查
`result.metadata.get("graceful_stop", False)`：

- 若 True：SHALL NOT 写 `seed_N.json`、SHALL NOT 写
  `seed_N_positions.json`、SHALL NOT 调用
  `DayCheckpointWriter.cleanup_partials`；SHALL 只 print 一行汇报
  "GRACEFUL_STOP after K day(s) — seed_N.json NOT written, partials
  preserved for resume"；SHALL NOT append `run_metrics` 到 aggregate
- 若 False（正常完成）：SHALL 走原路径——写 seed_N.json + 写
  positions + cleanup_partials + append run_metrics

audit 工具 SHALL 把 "graceful_stop 后没有 seed_N.json 但有
day_*.partial.json" 识别为 INTERRUPTED（可 resume）而非 DONE。

#### Scenario: graceful_stop=True 时跳过所有写
- **WHEN** worker 跑完 day 0-9 后收到 SIGUSR1，`result.metadata.graceful_stop`
  == True
- **THEN** `seed_N.json` SHALL NOT 存在；`seed_N_positions.json` SHALL NOT
  存在；`seed_N_day0..9.partial.json` SHALL 完整保留；aggregate.json 中
  对该 seed 的贡献 SHALL 为空（不在 runs list）

#### Scenario: graceful_stop=False 时正常写
- **WHEN** worker 跑完 day 0-13，`result.metadata.graceful_stop` == False
- **THEN** `seed_N.json` SHALL 存在并含完整 14 day result；`day_*.partial.json`
  SHALL 被 `cleanup_partials` 清除（final 是 source of truth）

### Requirement: worker 必须有 RSS 阈值自重启机制

`MultiDayRunner` SHALL 在 `run_multi_day` 注册一个 on_tick_end hook
（`_init_memory_management_hooks`），在 hook 里：

- 当环境变量 `RSS_RESTART_MB > 0` 时，每
  `RSS_CHECK_EVERY_N_TICKS`（默认 50）tick 量一次 self RSS（用
  `resource.getrusage` 或等价跨平台 API）
- 当 RSS > `RSS_RESTART_MB` MB 时，SHALL 设置
  `self._graceful_stop_requested = True`，让既有 graceful_stop 路径自然
  退出（写 partial + 退出 0）
- 当环境变量 `GC_EVERY_N_TICKS > 0`（默认 200）时，每 N tick 跑一次
  `gc.collect()` 并 log freed cycles

外部 launcher / LaunchAgent SHALL 在下次巡检 tick 看到 PID 不存在 +
有 snapshot/partial → spawn replacement（complement 的 constructive
recovery 行为）；effect 是每 worker RSS oscillates around threshold
而不是单调爬升。

`RSS_RESTART_MB=0`（默认 off）SHALL 完全禁用 RSS 监控，保持向后兼容。

#### Scenario: RSS 超阈值触发 graceful_stop
- **WHEN** `RSS_RESTART_MB=100`、worker 跑到 RSS 120 MB（mock
  `resource.getrusage` 返回 120 MB）
- **THEN** 下一次 RSS check tick SHALL 设 `_graceful_stop_requested=True`；
  worker SHALL 在当前 tick 末尾退出；写出 partial；退出码 0

#### Scenario: 默认 off 不动行为
- **WHEN** `RSS_RESTART_MB` unset 或 == 0
- **THEN** worker SHALL 不发生 RSS-driven graceful stop；
  `_graceful_stop_requested` SHALL 永远是 False（除非外部 SIGUSR1）

#### Scenario: gc.collect 周期触发
- **WHEN** `GC_EVERY_N_TICKS=10`、worker 跑到 tick_global=20
- **THEN** `_init_memory_management_hooks` 注册的 hook SHALL 已经调用过
  `gc.collect()` 至少 2 次；log SHALL 含 "[gc] tick_global=10" / "[gc]
  tick_global=20" 字样

### Requirement: publishable mode 必须默认 enable RSS hard cap

`tools/run_variant_suite.py` SHALL 在 `--mode publishable` 时检测环境
变量 `RSS_RESTART_MB`：未显式设置或值为 `0` 时 SHALL 自动 set 为
`10000` (10 GB)。

dev mode 不强制（保持默认 0 = 不启用），允许 dev 临时实验不被打断。

env override 仍然生效：`RSS_RESTART_MB=20000` 显式设可拉高，
`RSS_RESTART_MB=0` 可在 publishable 关闭（仅 advanced 场景）。

#### Scenario: publishable 自动设 10000
- **WHEN** 跑 `python tools/run_variant_suite.py --mode publishable ...`
  且 env RSS_RESTART_MB 未设
- **THEN** worker subprocess SHALL 启动时看到 `RSS_RESTART_MB=10000`；
  MultiDayRunner._init_memory_management_hooks SHALL 注册 RSS check
  hook（既有逻辑）

#### Scenario: publishable 但用户显式 override
- **WHEN** 跑 `RSS_RESTART_MB=5000 python ... --mode publishable`
- **THEN** worker SHALL 看到 `RSS_RESTART_MB=5000`（用户值优先）

#### Scenario: dev mode 不强制
- **WHEN** 跑 `--mode dev` 且 env 未设
- **THEN** worker SHALL 看到 `RSS_RESTART_MB=0`（or unset）；不撞顶

### Requirement: gc.collect() 后必须调 malloc_zone_pressure_relief

`MultiDayRunner._init_memory_management_hooks` SHALL 在 `gc.collect()`
之后立即调用 platform-specific malloc pressure relief：

- macOS: `ctypes.CDLL("libc.dylib").malloc_zone_pressure_relief(None, 0)`
- Linux: `ctypes.CDLL("libc.so.6").malloc_trim(0)` (TODO follow-up;
  非阻塞，本 change macOS 优先)
- Windows / 其它: skip silently

任何 ctypes call 失败 SHALL 包 try/except：第一次失败时 log warning，
后续 silent skip（避免每 200 tick 一次 warning 刷屏）。

#### Scenario: macOS 调用成功
- **WHEN** 跑在 macOS 且 GC_EVERY_N_TICKS=10 时跑到 tick_global=10
- **THEN** gc.collect 后立刻 malloc_zone_pressure_relief 被调；no exception

#### Scenario: ctypes 调用失败 fallback
- **WHEN** mock ctypes.CDLL raise OSError
- **THEN** run SHALL NOT crash；log warning 一次；后续 tick 静默 skip

#### Scenario: 非 macOS 平台 skip silently
- **WHEN** sys.platform == "linux" 且 malloc_trim 不可用
- **THEN** SHALL fallback warn 一次；不抛

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

