## Why

2026-05-14 启动的 D1' 全量 run（1000 agent × 14 day × 4 variant × Gemini 3.1
Flash Lite × 4 worker）跑到 5-15 中午**3/4 variant 因 google-genai async SDK
+ httpx 连接池 CLOSE_WAIT 累积导致死锁**——`asyncio.wait_for(45s)` 只能取消
单个 await，无法修复被毒化的连接池，整 worker 进入"取消 → 重试 → 取消"
无限循环。**72 计算小时白费、0 个 seed JSON 落地**。详见
[`docs/sessions/2026-05-15-d1-gemini-incident.md`](../../../docs/sessions/2026-05-15-d1-gemini-incident.md)。

D2 publishable run（DeepSeek × 15 seed × 14 day × 1000 agent）正在跑，预计
60-80h wall time——再踩同样的坑就是项目级灾难。

三个根因都尚未契约化：

1. **scale-only bug 现状**：50-agent smoke 触发不到（连接池毒化在数百万 LLM
   call 量级才饱和），1000-agent × 14d full 跑几小时就撞。没有 1000-agent
   pre-flight smoke gate。
2. **API 重试三处实现不一致**：Gemini 是 `asyncio.wait_for(45s)` + 手写
   1-retry；DeepSeek 是 openai SDK `timeout=45 max_retries=1`；Anthropic 完
   全靠 SDK 默认值。retryable / fatal 分类没统一，per-key 熔断没有。
3. **无 per-day checkpoint**：14-day run 是"全有或全无"——死锁/崩溃/Ctrl-C
   发生在 dump JSON 之前就是 100% 数据丢失，无法从最近天恢复。

热修复（在不丢已跑数据的前提下 kill + 修配置 + 续跑）是 publishable 阶段
的**必备能力**，本 change 把它从"事后救火脚本"提升为正式契约。

**Chain-Position**：`infrastructure`（不引入新主边界；为 attention-main 主链
+ 三层上下游提供可靠的实验执行底座，类比已 archive 的 `multi-day-simulation`
的位置）。

## What Changes

### 1. LLM 客户端连接池硬化（修 deadlock 根因）

- `tools/tier_llm_factory._GeminiTierClient` 注入自定义 `httpx.AsyncClient`，
  限制 `max_keepalive_connections=0` 禁止 socket 复用（断 CLOSE_WAIT 累积
  路径）；同时把超时/连接上限从 SDK 默认值显式接管
- 周期性 client 回收：所有 tier client 每 `recycle_after_calls`（默认 1000）
  次 call 主动 `aclose()` 重建底层 httpx，清残留状态
- **统一连接池契约**：所有 provider（Gemini / DeepSeek / Anthropic）SHALL 显式
  声明 `max_connections / max_keepalive_connections / connect_timeout /
  read_timeout / pool_timeout`，禁止隐式 SDK 默认值
- 多 key 轮询扩展到 Gemini：新增 `GEMINI_API_KEYS`（逗号分隔）与 DeepSeek
  对齐；单 key 被 4 worker 抢的毒化叠加路径关闭

### 2. API 重试统一化

- 新增 `synthetic_socio_wind_tunnel.run_resilience.retry.RetryPolicy`（Pydantic
  frozen 模型）：`max_attempts / base_backoff / max_backoff / jitter_ratio /
  retryable_exceptions / fatal_exceptions`
- 三个 tier client（Gemini / DeepSeek / Anthropic）SHALL 共用同一 `RetryPolicy`
  实例，由 `build_tier_clients(...)` 注入
- retryable：`TimeoutError`、`ConnectionError`、HTTP 429 / 5xx、transient TLS
- fatal：4xx（除 429）、auth error、parse error → 立刻抛、不计入 retry 预算
- per-key 熔断：单 key 连续 `circuit_break_threshold`（默认 5）次失败短暂
  下线（默认 5 min），其他 key 顶上；冷却后半开探测

### 3. Per-day checkpoint（热修复基石）

- `MultiDayRunner` 的 `on_day_end` hook **MUST** 写
  `seed_{N}_day{D}.partial.json`，含至当日为止的 RunMetrics 部分快照 +
  Ledger 状态摘要 + MemoryStore 序列化
- 死锁 / 崩溃 / SIGKILL / Ctrl-C 后，`tools/run_variant_suite.py --resume`
  能从最近 partial 接着跑，不必从 day 0 重跑
- 整 variant 完成（最终 `seed_{N}.json` + `aggregate.json` 落地）后 partial
  SHALL 被清掉，只留最终产物

### 4. Run 健康监控（自动探活）

- 新增 `tools/audit_run_health.py`：扫描 in-progress run 的 worker pid，检查
  process state（`UN` = uninterruptible 危险）、最近 log 行距今静默时长
  （> 30 min 告警）、CLOSE_WAIT TCP 累积（fd > `ulimit -n` × 60% 告警）、
  最近 N 次 LLM call 成功率（< 50% 告警）
- 可被 cron / launchd / Makefile target 调起；也可手动单次跑
- 退出码 0=健康 / 1=警告 / 2=疑似死锁（用于 CI / 监控集成）

### 5. 热修复协议

- **Graceful-stop 信号**：worker 接 `SIGUSR1` SHALL 跑完当前 tick → flush
  checkpoint → `exit(0)`（区别于 `SIGTERM`/`SIGKILL` 的强终止）
- **配置热重载**：`tier_llm_factory` 的连接池/重试参数 SHALL 从环境变量读
  （`RESILIENCE_RETRY_*` / `RESILIENCE_POOL_*`），重启 worker 即生效，无需
  改代码重新打包
- **`--resume` 语义化**：默认从最近 `*.partial.json` 接着跑；
  `--resume-from-day=N` 显式指定起点；旧 run 无 partial 时降级到 day 0
  并 stderr 打印警告

### 6. Pre-flight 1000-agent × 1d full smoke

- 新增 `tools/preflight_full_smoke.py`：跑 1 day × **1000 agent**（项目固定
  参数，非 100）× 全 4 variant × 1 seed，配置与 publishable 完全一致
- publishable 模式 SHALL 强制先跑 preflight；`--skip-preflight` 仅开发模式
  可用，publishable 模式忽略该 flag 并 stderr 警告
- 退出码 0 才允许进入 publishable run

## Capabilities

### New Capabilities

- `run-resilience`: publishable run 的抗故障基础设施——LLM 客户端连接池
  硬化、统一 RetryPolicy + per-key 熔断、graceful-stop 信号、配置热重载、
  per-tick / per-day 健康审计。对外提供 `RetryPolicy`、`ResilientClientWrapper`、
  `HealthAudit`、`HotfixSignalHandler` 四个公共类型 + `tools/audit_run_health.py`
  + `tools/preflight_full_smoke.py` 两个 CLI。

### Modified Capabilities

- `multi-day-run`: 新增 per-day checkpoint requirement——`on_day_end` hook
  MUST 落 `seed_{N}_day{D}.partial.json`；`MultiDayRunner` 新增 `resume_from`
  构造参数；suite 完成时清理 partial 文件

（`tools/run_variant_suite.py` 的新 CLI flag `--resume` / `--resume-from-day`
/ `--skip-preflight` 由 `run-resilience` capability 直接规定，不修改既有
`suite-wiring` spec 的契约——后者的"不改已归档 capability"原则保持。）

## Impact

- **新代码**
  - `synthetic_socio_wind_tunnel/run_resilience/` 新模块（`__init__.py` /
    `retry.py` / `circuit_breaker.py` / `health.py` / `hotfix.py` /
    `checkpoint.py`）
  - `tools/audit_run_health.py`（新 CLI）
  - `tools/preflight_full_smoke.py`（新 CLI）
- **修改**
  - `tools/tier_llm_factory.py`：所有 `_*TierClient` 接入统一 `RetryPolicy` +
    自定义 `httpx.AsyncClient`；Gemini 加 multi-key 支持
  - `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`：`MultiDayRunner`
    加 `resume_from` / checkpoint 写盘 / 信号处理
  - `tools/run_variant_suite.py`：`--resume` / `--resume-from-day` /
    `--skip-preflight` flag + publishable 强制 preflight
  - `synthetic_socio_wind_tunnel/__init__.py`：re-export 新公共 API
- **测试**
  - `tests/test_run_resilience_retry.py`（RetryPolicy / 熔断 / fatal 立即抛）
  - `tests/test_run_resilience_checkpoint.py`（partial 写 / resume 读 / 清理）
  - `tests/test_run_resilience_health.py`（CLOSE_WAIT 累积模拟 / 静默检测）
  - `tests/test_run_resilience_hotfix.py`（SIGUSR1 graceful stop / env 热重载）
  - `tests/test_tier_factory_resilience.py`（Gemini multi-key / 显式 httpx 限制）
- **依赖**
  - 既有 `httpx`（openai 已经传递依赖，无需新增）
  - 既有 `pydantic`（RetryPolicy 用）
- **配置 / 文档**
  - `.env.example` 新增 `GEMINI_API_KEYS` / `RESILIENCE_RETRY_MAX_ATTEMPTS` /
    `RESILIENCE_POOL_MAX_KEEPALIVE` 等示例
  - `docs/agent_system/` 新增一份 `15-run-resilience.md` 简介
- **前置依赖**：无（独立基建 change；与 `multi-day-simulation` 平级，依赖它
  已落地的 `MultiDayRunner` / `on_day_end` hook）
- **下游依赖**：D2 之后的所有 publishable run 都将依赖本 change；未来 D3 /
  publishable v2 等长跑契约依赖
- **向后兼容**：
  - `tier_llm_factory.build_tier_clients()` 旧调用零改动（新参数都有默认值）
  - 旧的无 partial 的 run 调 `--resume` 时降级到 day 0 + 打印警告
  - 单日 `Orchestrator.run()` 行为完全不变（仅 `MultiDayRunner` 受影响）

## Non-goals

- 不重写整个 `tier_llm_factory`，在 `_GeminiTierClient` / `_DeepSeekTierClient`
  之上增量改
- 不引入新 LLM provider
- 不改 Atlas / Ledger / Perception / Collapse（与 CQRS 主链无关）
- 不做 distributed coordinator（multi-machine 跑暂不在内）
- 不动 metrics / fitness 报告格式
- 不做"自动热修复 bug 并无人值守续跑"——本 change 只保证 kill + 修配置 +
  restart 的损失 ≤ 1 模拟天
- 不做 GPU / 本地模型回退路径
