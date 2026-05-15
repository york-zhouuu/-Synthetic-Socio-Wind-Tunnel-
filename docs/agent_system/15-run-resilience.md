# 15 · 跑得稳：抗故障与热修复（run-resilience）

> **白话名**：跑长跑不死人的基建
>
> **技术名**：run-resilience（2026-05-15 D1' 事故后引入）

## 是什么

publishable run 是 1000 agent × 14 day × 4 variant × 30 seed 的长跑，
单机预估 60-80 小时墙钟时间。这种长跑要面对的现实是：

- **LLM provider 的连接会偶尔被服务端切断**（idle timeout / 负载均衡轮换）。
  如果客户端的连接池没把"死连接"踢出去，新请求会一直拿到死 slot，整个
  worker 进入"取消 → 重试 → 取消"的死循环——D1' 当天就是这么坏的。
- **bug 都是 scale-only**：50 agent 的 smoke 跑不出来的死锁，1000 agent
  几小时就撞——D1' 之前的所有 smoke 都过了。
- **14 天是"全有或全无"**：跑到第 11 天死锁，0 个 seed JSON 落地，前面
  的计算全白费。

本基建模块（`synthetic_socio_wind_tunnel/run_resilience/`）就是把上述问题
全部从"事后救火"提升为"开工前的契约 + 跑起来就在背景里值班的探活"。

**技术注脚**：模块由 5 部分构成：`retry.RetryPolicy`（统一退避策略）/
`circuit_breaker.PerKeyCircuitBreaker`（多 key 熔断）/
`checkpoint.DayCheckpointWriter`（per-day partial JSON 写盘）/
`health.HealthAudit`（pid / log / TCP / 内存的探活）/
`hotfix.HotfixSignalHandler`（SIGUSR1 优雅停机协议）。

## 解决什么问题

> "我开了一个跑了 4 小时还没结果的长跑，到底它是真在跑、还是已经卡死了我自己不知道？"

> "上次 Gemini 全 4 worker 死了 3 个，我看了 7 小时才发现——下次能不能它自己报警，或者干脆别死？"

> "如果真的死了，能不能不丢之前 10 天的数据？"

> "我改了配置想让它立刻生效，要不要把整个 run 杀掉重来？"

## 意义

没有这一层，整个 publishable 实验是赌运气。有了它：

| 失效模式 | 之前 | 现在 |
|---|---|---|
| Gemini 连接池毒化 | 14 day → 72 小时全损 | **不会发生**（keepalive=0 阻断累积路径） |
| DeepSeek 单 key 触发限流 | 全 worker 堵在那个 key 上 | 熔断 + multi-key 轮询自动绕开 |
| 进程 7 小时无新 log 没人看 | 用户半夜起来巡查 | `audit_run_health.py` 自动判 deadlock + 提示 SIGUSR1 |
| 任意时刻杀进程 | 失去当前进度 | 最多丢当天 1 天数据，`--resume` 续跑 |
| 改 retry / 池子参数 | 改代码、重新打包 | 改环境变量、重启即生效 |
| publishable 跑出去才发现挂 | 浪费几十小时 | 1000-agent × 1-day preflight 提前 15 分钟暴露 |

## 五件防御工事

### 1. 连接池硬化：`max_keepalive_connections = 0`

D1' 根因是 google-genai async SDK + httpx 的连接池在 macOS kqueue 下不
正确处理 server 主动 close 的 socket，导致死 fd 累积成 CLOSE_WAIT 池子被
毒化。**修复**：所有 provider（Gemini / DeepSeek / Anthropic）的内部 httpx
async client SHALL 注入 `max_keepalive_connections=0`，每次 call 用完
立即 close socket——CLOSE_WAIT 没机会累积。

代价是每次 call 多一次 TLS handshake（~80-150ms），整体慢 10-20%。
60-80h × 1.2 = 72-96h，比 100% 数据丢失划算得多。

技术细节：通过 google-genai 2.3.0+ 官方 API `HttpOptions(httpx_async_client=...)`
注入。代码见 `tools/tier_llm_factory.py::_GeminiTierClient`。

### 2. 统一 RetryPolicy + per-key 熔断

之前三家 provider 各写各的 retry：Gemini 用 `asyncio.wait_for(45s) + 1-retry`、
DeepSeek 用 openai SDK 的 `max_retries=1`、Anthropic 完全依赖 SDK 默认。
**修复**：三家共用一个 `RetryPolicy` 实例，定义：

- retryable: `TimeoutError`、`ConnectionError`、HTTP 408/425/429/5xx
- fatal: HTTP 4xx（除 429）、auth error → 立刻抛、不计入重试预算
- 退避：指数 + 抖动，capped 8 秒

外加 `PerKeyCircuitBreaker`：单个 API key 连续 5 次失败 → 短暂下线 5 分钟，
其他 key 顶上。状态机：closed → open → half-open → 重新评估。

### 3. Per-day checkpoint + `--resume`

`MultiDayRunner.run_multi_day` 每天结束在 `on_day_end` hook 之前同步落
`seed_{N}_day{D}.partial.json`（包含 RunMetrics 部分快照 + ledger 状态
摘要 + provider 元数据）。

死锁 / 崩溃 / SIGKILL / Ctrl-C 后，`run_variant_suite.py --resume` 会：

1. 扫该 variant 目录找最新 partial
2. 用 `resume_from = partial.day_index + 1` 构造 MultiDayRunner
3. 从那天接着跑

整个 variant 完成（落最终 `seed_{N}.json` + `aggregate.json`）后，partial
被清理。

### 4. SIGUSR1 graceful-stop 协议（"热修复"）

worker 收到 `kill -USR1 <pid>` 后：

1. signal handler 仅设置 `runner._graceful_stop_requested = True`（async-signal-safe）
2. 主循环下一 tick 末看到 flag → 不再启动 tick → 写当天 partial → 返回截断 result
3. 进程退出 0，调用方可用 `--resume` 接续

环境变量都从 `RESILIENCE_*` 读，改完后 graceful-stop + restart 即生效，
**不必改代码**。这就是用户最关心的"热修复"。

`SIGTERM` 行为不变（Python 默认 → KeyboardInterrupt 强终止）。
`SIGKILL` 走 OS 路径强杀——但有 per-day partial 兜底。

### 5. 探活与 preflight gate

**`tools/audit_run_health.py <run_dir>`**：扫 worker pid + log mtime +
CLOSE_WAIT TCP 数 + 进程状态（macOS 'U' / Linux 'D' = uninterruptible
sleep = 危险）。退出码 0 / 1 / 2 对应 healthy / warning / suspected_deadlock。
可以塞进 cron / launchd 自动巡检；suspected_deadlock 时会在 stdout 打印
具体的 SIGUSR1 / SIGKILL 命令行。

**`tools/preflight_full_smoke.py --provider deepseek`**：1000 agent × 1 day
× 全 4 variant × 1 seed 的最小 publishable 复刻。**publishable 模式
（`--agents 1000 --num-days 14`）SHALL 强制先跑 preflight**，`--skip-preflight`
被忽略（D1' 教训：scale-only bug 只在 1000 agent 才出现，渐进式 smoke
触发不到）。preflight ~15-20 min wall，比 72h publishable 的 0.5% 成本，
换 100% 死锁前置发现率。

## 用法速记

```bash
# 0. 先建议在 .env 配 GEMINI_API_KEYS=k1,k2,k3 + DEEPSEEK_API_KEYS=k1,k2 启
#    用 multi-key 轮询（默认 single key 也可以跑）
# 1. 启动 publishable run（preflight 自动跑）
python tools/run_variant_suite.py \
  --variants baseline,hyperlocal_push,global_distraction,phone_friction \
  --seeds 15 --agents 1000 --num-days 14 \
  --phase-days 4,6,4 --mode publishable --use-aitown \
  --aitown-provider deepseek --num-protagonists 500 --workers 4 \
  --suite-name d3_deepseek_15seed

# 2. 另一个终端定期巡检
watch -n 600 'python tools/audit_run_health.py data/experiments/<run_dir>/'

# 3. 如发现死锁 / 想改配置：SIGUSR1 优雅停机
kill -USR1 <worker_pid>

# 4. 改 .env（或直接 export）：
export RESILIENCE_POOL_MAX_CONNECTIONS=400  # 示例：调小连接池
# 5. 重启续跑
python tools/run_variant_suite.py --suite-dir <existing_dir> --resume ...
```

## 与其他能力的对接

- `multi-day-run`：本 change 给 MultiDayRunner 加 `output_dir` / `resume_from`
  / `_graceful_stop_requested` 三个 hook。原 spec 行为零回归。
- `suite-wiring`：CLI flag `--resume-from-day` / `--skip-preflight` 由
  本 change 加入 `run_variant_suite.py`，原 spec 不动（无 spec 修改）。
- 公共 API：`RetryPolicy` / `PerKeyCircuitBreaker` / `DayCheckpointWriter` /
  `HealthAudit` / `HotfixSignalHandler` 通过 `synthetic_socio_wind_tunnel/__init__.py`
  re-export，外部 `from synthetic_socio_wind_tunnel import RetryPolicy` 即可。
- `fitness-audit`：新增 `phase2-gaps.run-resilience.*` 5 个探针，
  全 PASS 即本 change 落地完整。

## 故事化背景

> 2026-05-14 15:29 启动 D1' 全量（1000 agent × 14 day × Gemini × 4 worker）。
> 5-15 11:47 起 3 个 worker 突然停 log。15:00 用户发现，16:00 确诊死锁，
> 17:00 SIGKILL 救回唯一还活着的 phone_friction。72 计算小时白费，0 个
> seed JSON 落地。
>
> 复盘锁定根因：google-genai async SDK + httpx 的连接池在 server 主动
> close 后留下 CLOSE_WAIT 死 fd，整池被毒化，`asyncio.wait_for(45s)` 取消
> 单个 await 但池状态不变——下一个 task 还是拿不到 slot，又超时——无限
> 循环。50-agent smoke 一直跑得好好的，因为毒化是百万级 LLM call 才饱和
> 的 scale-only bug。
>
> 一周内把方案契约化进 OpenSpec，两天写完代码 + 测试 + 文档。从此每个
> publishable run 都必须先过 1000-agent × 1-day preflight gate；跑期间
> `audit_run_health` 探活；卡了 SIGUSR1 救出最近一天的数据 + 改配置 +
> `--resume` 续跑。
>
> 一句话：把"7 小时不知道死没死" 变成 "5 分钟一报、想停就停、停了能续"。

## 参考文档

- [`docs/sessions/2026-05-15-d1-gemini-incident.md`](../sessions/2026-05-15-d1-gemini-incident.md) — 事故详细复盘 + 根因 + 4 层修复方案
- [`docs/HANDOFF_2026_05_15.md`](../HANDOFF_2026_05_15.md) — 事故当日交接
- [`openspec/specs/run-resilience/spec.md`](../../openspec/specs/run-resilience/spec.md) — 正式契约（archive 后生效）
- [`openspec/changes/run-resilience/`](../../openspec/changes/run-resilience/) — 设计 + 任务列表
