## Why

D2 attempt 6 (2026-05-19 12:08:22) 真实根因，**经 23:00+ 二次 log 取证
确认**：4 个 worker 在 2 秒内同时 spawn → 每 worker 500 protag agents
→ 同一时刻 ~2000 个并发 LLM call 打 DeepSeek API → 触发 server-side
防 burst → 部分 TCP silent drop → SDK 看到 `openai.APIConnectionError`
→ 多个 key 进 cooldown → 8 keys 全 open → `FallbackBudgetExceeded`
worker 自杀 → resume_publishable.py 又重新 spawn → 循环。

证据（worker_phone_friction.log line 73-138, 12:08 spawn 那段）：

```
=== resume_publishable spawn @ 2026-05-19T12:08:22 ===
[aitown] wired (lazy hint refs attached)              ← line 82, setup 完成
do_something LLM returned unparseable response ...    ← line 83-85, DeepSeek
                                                          有应答，但 JSON 坏
do_something LLM failed: APIConnectionError ...       ← line 86+, 一波抖动
... (大量错误)
op handler raised: all 8 keys open                    ← line 138, 8 keys 全死
```

**setup 到所有 key cooldown 只用了 ~55 行 log**——这不是"长跑 12 天才
死"的累积失败，是 **spawn-burst 自残**。

CLAUDE.md 早就警告过同时 spawn 多 worker 的危险（`snapshot-resume-ram-peak`
不变量：staggered spawn ≥ 5 min），但只针对 RAM 视角，而且**没有在代码
里强制**——只是 docstring 里写"current implementation does NOT stagger"
让人记得手动间隔。当 `resume_publishable.py` 5 分钟 LaunchAgent 周期内
遇到多个 INTERRUPTED cell 时，依然会**同时 spawn**所有。

→ 同一根因，两个 failure mode：
1. **RAM peak**（已记 invariant）：4 worker × 3.5GB snapshot deserialize
   = 50-100GB peak → swap → 拖死
2. **LLM API burst self-DDoS**（这次发现）：4 worker × 500 protag agents
   × 立刻发 LLM call = 2000 并发 → server protective measure → TCP drop

**修复**：在 spawn 代码里硬强制最小间隔。**单一改动同时 cover 两个
failure mode**——这是为什么要做成独立 OpenSpec change（而不是顺手在
retry-network-blip-tolerance 里塞）。

## What Changes

- **`tools/resume_publishable.py::_spawn_resume_worker`** 加 spawn-stagger
  guard：spawn 前检查 last-spawn timestamp（持久化在
  `~/Library/Logs/swt-resume-watchdog-last-spawn.json`），若距上次 spawn
  < `min_spawn_spacing_secs` 则跳过本轮，返回特殊 sentinel "deferred"
  并 log 原因 + 计算下次可 spawn 时间。
- 主循环遇到多个 INTERRUPTED cell 时**串行**处理：第 1 个 spawn 后
  立刻更新 last-spawn timestamp；第 2/3/4 个看到时间窗未到自动 defer
  到下次 LaunchAgent 5-min 周期。
- argparse 加 `--min-spawn-spacing-secs INT`（默认 300），env override
  `RESILIENCE_MIN_SPAWN_SPACING_SECS`。
- **`tools/run_variant_suite.py` `_run_worker` thread-pool fan-out 路径**
  加同样 stagger 守护：`ThreadPoolExecutor.submit` N 个 worker 时，
  worker 之间也强制 `time.sleep(min_spawn_spacing_secs)` 间隔（用
  staggered submit 实现，不阻塞外层 coordinator）。
- 不增加新依赖。

**NOT** in scope:
- 不改 LLM client 端的并发 limit（worker 内部并发是 by design，单
  worker 内 500 agents × 1 LLM call/tick 是正常负载）
- 不改 retry policy（独立 `retry-network-blip-tolerance` change）
- 不动 `LLMHealthTracker` / `FallbackBudgetExceeded` 阈值
- 不改 watchdog kill 逻辑（[[monitor-as-control-plane]]）
- 不引入"集中式 worker registry"——文件锁式 last-spawn timestamp 已
  足够 single-host scope

## Capabilities

### New Capabilities

- `worker-spawn-coordination`: spawn timing 协调能力。定义最小间隔
  contract + 持久化 last-spawn timestamp 协议 + thread-pool 内部 stagger
  rules，覆盖 `resume_publishable.py` LaunchAgent 路径和
  `run_variant_suite.py --workers N` 路径。

### Modified Capabilities

无。

## Impact

**Affected code**:
- `tools/resume_publishable.py` —— `_spawn_resume_worker` 加 stagger
  guard + 主循环改为串行处理多 cell
- `tools/run_variant_suite.py` —— `_run_worker` ThreadPool 提交时
  加 staggered submit
- `CLAUDE.md` —— 扩展 `snapshot-resume-ram-peak` 不变量段，新增 LLM
  API burst self-DDoS 视角

**Affected behavior (positive)**:
- 4 个 INTERRUPTED cell 不再同一秒同时 spawn —— 第 1 个立刻 spawn，
  第 2 个在 5+ min 后下个 LaunchAgent 周期 spawn，第 3/4 个同理。
- 单次 publishable run worker pool 启动从"4 个 worker × 500 agents
  × T=0 全部 LLM call"变成"分批 staggered"，并发峰值降为 1/4
- 同时 cover `snapshot-resume-ram-peak`：4 worker × 3.5GB snapshot
  不再同时 deserialize，RAM peak 自然降下来

**Affected behavior (negative / trade-off)**:
- 4 cell 全部 spawn 完成时间从"立刻"变成"~15-20 min"（4 × 5 min stagger）
- 单次 run 总体 wall time 增加 ~15 min（在 18-24 hour 总 wall 里 < 2%）
- 这是可接受 trade-off：换稳定性

**Dependencies**: 无新依赖。

**Test impact**: 估计 ~12 个新 test：unit (timestamp persistence /
spacing check / env override) + integration (mock spawn N cells with
varying stagger configurations) + fault injection (corrupted timestamp
file / clock skew) + behavioral (worker thread-pool stagger order)
