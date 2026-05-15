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
- `retryable_http_statuses: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)`
- `fatal_http_statuses: tuple[int, ...] = (400, 401, 403, 404, 422)`

`RetryPolicy` SHALL 提供方法 `next_backoff(attempt_idx: int) -> float`，返回
指数退避 + jitter 后的下一次 sleep 秒数，且永不超过 `max_backoff_seconds`。

`RetryPolicy` SHALL 提供方法 `classify(exc: BaseException) ->
Literal["retryable", "fatal", "unknown"]`，按 retryable / fatal 规则归类。
status code 提取方式 SHALL 支持 openai SDK `APIStatusError.status_code`、
google-genai `ServerError.code`、httpx `HTTPStatusError.response.status_code`
三种格式。

#### Scenario: 默认参数构造
- **WHEN** `RetryPolicy()` 默认构造
- **THEN** `max_attempts == 3`；`retryable_http_statuses` 至少含 429 / 500 /
  502 / 503 / 504；`fatal_http_statuses` 至少含 400 / 401 / 403 / 404

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

