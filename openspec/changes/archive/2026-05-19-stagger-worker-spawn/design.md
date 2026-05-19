## Context

D2 attempt 6 (2026-05-19 12:08:22) 自残复盘：`resume_publishable.py`
LaunchAgent fire 时遇到 4 个 INTERRUPTED cell（hyperlocal_push /
phone_friction / global_distraction / baseline 各一个 seed 中断），
当时主循环对每个 cell 直接调 `_spawn_resume_worker`，间隔仅
`time.sleep(2)`（用于检测 spawn 立刻 crash 的健康检查）。

结果 2 秒内 4 个独立 Python 进程都进入 setup → load atlas → load
snapshot → wire LLM clients → fire first batch of `do_something`
LLM call。每个 worker 内部 500 protag × 1 LLM/tick concurrent = 500
in-flight HTTP request per worker。**4 worker × 500 ≈ 2000 个 HTTP
POST 同一秒打 api.deepseek.com**。

DeepSeek API 在这种 burst 下：
- 部分请求正常返回（worker 看到 `unparseable response` —— LLM 自由发挥）
- 部分请求遭遇 server-side 防 burst 措施（silent TCP drop / TLS handshake
  abort / connection refused）→ httpx 抛 `ConnectError` → openai SDK 包
  成 `APIConnectionError`
- 没看到 HTTP 429，因为防 burst 是 TCP 层 drop 不是应用层 throttle

每个 APIConnectionError → 一个 key 被 circuit breaker 标 failure →
key 进 cooldown。8 keys 在 ~55 行 log 内全部 cooldown → 之后所有 LLM
call 都 short-circuit AllKeysOpenError → tracker 100% fallback rate →
12 个 tick 后 `FallbackBudgetExceeded` → 4 workers 全部自杀。

LaunchAgent 5 分钟后再次 fire → 看到 4 个 INTERRUPTED → 又同时 spawn
→ 同样循环。如此往复直到 human 介入。

CLAUDE.md 已经有相关 invariant (`snapshot-resume-ram-peak`)，但只覆盖
RAM 视角，且**没在代码里强制**，只是 docstring 提醒"current
implementation does NOT stagger; if you need staggering, add it before
spawning more than 2 mid-run workers at once"。这种"约定式约束"在
LaunchAgent 自动运维场景下不可靠 —— 我们需要 in-code enforcement。

## Goals / Non-Goals

**Goals:**
- spawn-burst 不再发生：跨 cell 的 spawn 间隔 ≥ 5 min（可配置）
- 单一改动同时 cover **LLM API burst self-DDoS** 和
  **snapshot-resume RAM peak** 两个 failure mode
- 持久化机制简单可靠（文件 timestamp），不引入新依赖、不需要进程间锁
- 适用两个 spawn 路径：`resume_publishable.py` (LaunchAgent driven) +
  `run_variant_suite.py --workers N` (suite-internal ThreadPool)
- 行为可观测：每次 defer 必须 log 原因 + 下次可 spawn 时间，方便监控

**Non-Goals:**
- 不引入分布式协调（Redis / etcd）—— single-host 假设
- 不改单 worker 内部的 LLM 并发模型（500 agents × 1 LLM/tick 是 by
  design）
- 不动 `LLMHealthTracker` 阈值 / circuit breaker cooldown
- 不替代 retry policy 的 transient failure 处理（独立 change）
- 不试图 spawn 之后再"补偿"——一旦 spawn 就让它跑完
- 不区分 spawn 类型（fresh vs resume）—— 都按同一 spacing 规则
- 不覆盖 ad-hoc 手动 `python tools/run_variant_suite.py` 调用 ——
  那是人触发，人负责 spacing

## Decisions

### D1: 文件式 timestamp，不用进程间锁

**选项**:
- (A) 持久化 last-spawn timestamp 到 JSON 文件，spawn 前读取 + 比较
- (B) 使用 `fcntl.flock` 文件锁包住整个 spawn 过程
- (C) 用 Redis / DB 做集中式 spawn-token bucket

**选定: A — JSON 文件 timestamp**

理由：
- (C) 引入额外依赖、运维负担；single-host 不需要
- (B) 锁的语义是"互斥"，不是"间隔"；要实现"间隔"需要加 sleep，但
  sleep 会阻塞 LaunchAgent，让本来无关的 cell 检查也被卡住
- (A) 读写 timestamp 文件是 O(1)，可以放在 spawn 决策点之前，决策
  失败立刻跳过本轮——LaunchAgent 5 min 后会再 fire，自然 retry
- (A) 缺点：文件写并发风险。但 `resume_publishable.py` 每 5 min 启动
  一个进程，进程内顺序处理 cell，**不存在两个 resume_publishable.py
  同时跑的场景**（LaunchAgent 已经 serialize）。`run_variant_suite.py
  --workers N` 是单进程内部，threading.Lock 防并发即可。

### D2: timestamp 文件位置 + 格式

**选定**: `~/Library/Logs/swt-resume-watchdog-last-spawn.json`

理由：
- 跟现有 `~/Library/Logs/swt-resume-watchdog.log` 同目录，运维统一
- 不进 repo（user-local state，不应跨机器同步）
- JSON 而非纯 timestamp string —— 留扩展空间 (e.g. 加 reason / spawned
  cell name 用于审计)

格式:
```json
{
  "last_spawn_monotonic": 1234567.89,   // time.monotonic()
  "last_spawn_iso": "2026-05-19T12:08:22+10:00",  // human readable
  "last_spawn_cell": {"seed": 42, "variant": "phone_friction"},
  "version": 1
}
```

**关键**: `last_spawn_monotonic` 是 process-relative，**跨进程不可比较**
—— 改用 `time.time()` epoch seconds（系统时钟）。其它字段 informational。

修正后:
```json
{
  "last_spawn_epoch": 1747623100.5,
  "last_spawn_iso": "2026-05-19T12:08:22+10:00",
  "last_spawn_cell": {"seed": 42, "variant": "phone_friction"},
  "version": 1
}
```

### D3: spacing default 300s (5 min)

**选定**: 300s 默认，env / arg 可调

理由：
- CLAUDE.md `snapshot-resume-ram-peak` 推荐"间隔 ≥ 5 min"
- LaunchAgent 5 min 周期天然 align —— 每周期 spawn 1 个，4 cell 全部
  起来需要 ~20 min wall (acceptable)
- LLM API rate-limit 角度：5 min 让 DeepSeek server-side counter 充分
  reset，下批 worker 进入"clean slot"
- 不应太长（>10 min）：单 cell INTERRUPTED 后恢复速度太慢

### D4: 多 INTERRUPTED cell 时的处理顺序

**选定**: 主循环遇到 INTERRUPTED 时按 `(seed, variant)` 字典序处理
**第一个**满足 spacing 的 cell；剩余的标 `deferred_due_to_stagger`
跳过本轮

理由：
- 简单 + 可预测：log 里能看到"本轮 spawn 了 seed=42/baseline，其它
  3 个 deferred 到下个 LaunchAgent 周期"
- 公平性：字典序稳定，不会"偏心"某个 cell
- 替代方案"按 INTERRUPTED 时间最早优先"需要额外 mtime 检查，复杂度
  不值

### D5: ThreadPool path 用 staggered submit

`run_variant_suite.py --workers N` 当前实现：

```python
with ThreadPoolExecutor(max_workers=n_workers) as pool:
    futures = {pool.submit(_run_worker, v): v for v in variants}
```

所有 future 立刻 submit → ThreadPool worker thread 立刻 grab → N 个
subprocess 同时 spawn。

**改造**: 把同步 submit 改为 staggered:

```python
with ThreadPoolExecutor(max_workers=n_workers) as pool:
    futures = {}
    for i, v in enumerate(variants):
        if i > 0 and stagger_secs > 0:
            time.sleep(stagger_secs)  # 在 coordinator thread sleep
        futures[pool.submit(_run_worker, v)] = v
```

trade-off: coordinator thread (main thread) 被 sleep 阻塞 ~15 min
（4 × 300s）。在 publishable run 18-24h wall 里这 15 min 是 < 2%。

替代方案"用 timer 异步 submit"会让代码复杂度暴增，不值。

### D6: 不强制串行 ad-hoc CLI 调用

**选定**: 只覆盖 LaunchAgent / suite-internal ThreadPool 路径

理由：
- ad-hoc 手动 `python tools/run_variant_suite.py --workers 4` 是
  user-triggered，人负责 spacing
- 强制 ad-hoc 路径也守 spacing 会让测试 / 实验场景痛苦
- env override (`RESILIENCE_MIN_SPAWN_SPACING_SECS=0`) 让 ad-hoc
  用户可显式关闭

但 suite-internal ThreadPool 路径仍要强制（即使 user 没用
LaunchAgent，suite 本身也会 spawn-burst）。

### D7: 不实现 token bucket / leaky bucket

理由：
- 5 min spacing 太长，不需要 burst-allowance；spacing = 5 min hard
  floor 已经够用
- token bucket 复杂度高、状态管理多，不值

## Risks / Trade-offs

**[R1] 第 1 个 LaunchAgent 周期 spawn 1 个 cell，剩 3 个 deferred —
但同 1 个 cell 在第 2 周期又被识别为 INTERRUPTED → 还是只 spawn 1 个**
→ Mitigation: 这是预期行为。LaunchAgent 5 min 周期是 spacing 的天然
  上限。所有 4 个 cell 全部 spawn 完成需要 ~20 min wall。这是 stability
  vs latency 的 trade-off，明确选 stability。

**[R2] timestamp 文件被外部 (e.g. 测试) 篡改导致 spacing 失效**
→ Mitigation: spawn 失败不写 timestamp（仅 success path 写）。读
  timestamp 时如果格式错误，log warning + fallback to "spawn allowed"
  —— 保守失败模式（宁可允许 spawn 也不锁死）。

**[R3] 系统时钟回拨 / NTP 调整导致 epoch 倒退**
→ Mitigation: 检查 `now - last_spawn > 0`；若负值则记 warning + 重置
  timestamp = now (i.e. 重新计时)。

**[R4] ThreadPool coordinator main thread sleep 阻塞 user signal
处理（e.g. Ctrl-C 响应延迟）**
→ Mitigation: sleep 拆成小段（1s × N），每段检查 `_graceful_stop_requested`
  flag。已经有现成 pattern 在 multi_day.py 用过。

**[R5] D2 attempt 6 实际事件可能除了 spawn-burst 外还有别的因素未覆盖**
→ Mitigation: 这是 partial fix 心态。承认 retry-network-blip-tolerance
  是 defense-in-depth 配合。如果 stagger 落地后仍出现类似事故，需要
  二次取证（加 timestamped logging）。

## Migration Plan

1. **部署**: 改 `resume_publishable.py` + `run_variant_suite.py` 后
   下次 LaunchAgent fire 即生效。如果当时已有 timestamp 文件冲突，
   stagger guard 读到任何 valid timestamp 都先尊重；新 spawn 会
   overwrite 它。
2. **验证 (dry-run)**: `python tools/resume_publishable.py --dry-run`
   模拟 4 个 INTERRUPTED cell → 应看到 1 个 "would spawn"，3 个
   "deferred_due_to_stagger"。
3. **验证 (实跑)**: 下次 publishable resume 起。监控
   `~/Library/Logs/swt-resume-watchdog.log` 的 spawn / deferred 比例。
4. **Rollback**: env `RESILIENCE_MIN_SPAWN_SPACING_SECS=0` 立刻
   restore 旧 behavior（一次性回退所有 stagger，cell 全部立刻 spawn）。

## Open Questions

- (闭合) 是否 ad-hoc CLI 调用也强制？答：D6 不强制，env 0 可关。
- (闭合) timestamp persist 用 JSON 还是 binary？答：D2 JSON。
- (闭合) coordinator thread sleep 是否阻塞？答：D5 接受 + R4 小段
  sleep 缓解。
