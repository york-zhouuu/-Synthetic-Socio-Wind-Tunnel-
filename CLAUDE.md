# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## 关键参数（事实校正）

- **agent 数量：1000**（不是 100；100 是 smoke 配置）
- **hyperlocal 推送半径：1000 米**（不是 500m）
- 14 天协议：4 baseline + 6 intervention + 4 post
- β rigor：**4 seed for publishable**（2026-05-18 由 10 再降到 4 — 单机内存 + Doubao 单 key 限制下平衡时间/资源；旧文档里的 "30 seed" / "10 seed" / "β=30" / "β=10" 已是过时表述）

任何对外文档/报告引用这两个数字时务必用 1000 / 1000m。

## 关键不变量（testing-rigor 2026-05-19）

写新 capability / 大 PR 提交前 SHALL 过 `tests/README.md` 的
**8 类问题清单**——pytest 全绿是必要条件，**远不充分**。本项目过去
7 个生产事故都在测试全绿的代码里。

8 类问题（每类对应一个真实事故 case study，详见
`docs/testing-philosophy.md`）：

1. **中断路径**测了吗？（SIGUSR1 / SIGTERM / cancel 不写假完整文件）
2. **启动期边界**测了吗？（WAL mtime < proc start time 的语义）
3. **资源 budget** 测了吗？（publishable-scale fixture 测 RSS / 时长）
4. **外部依赖失败路径** mock 了吗？（subprocess / HTTP / DB 至少 3 个失败 mode）
5. **并发 / atomic 操作 race** 测了吗？（threading.Barrier + 10 轮迭代）
6. **long-running 数据结构有界性**测了吗？（dict/list 跑 14 day 后 size < threshold）
7. **smoke 覆盖最坏一天**了吗？（不只是 day 0，覆盖 day 11+ peak）
8. **不变量配源码级 + 行为级双层 guard** 了吗？（grep test + mock test）

**spec scenario 写作约束**（同源同检验）：每个
`#### Scenario:` 的 WHEN/THEN 子句 SHALL 可机器映射到一个 test fn；
不允许"待人工 review"作为 outcome。

正例：`tests/test_harden_invariants.py`（3 不变量 × 2 层 = 6 tests）；
`tests/test_simulation_checkpoint.py::test_concurrent_writes_no_corruption`
（10 轮 barrier 并发 race test）。

反例：本项目截至 2026-05-19 仍**缺**的高优 test（见
`docs/testing-philosophy.md` 附录）：

- `test_concurrent_resume_ram_budget.py`（问题 3）
- `test_find_pid_ps_failure_modes.py`（问题 4）
- `test_dialogue_service_bounded_long_run.py`（问题 6）
- `test_smoke_publishable_day11.py`（问题 7）

下次开 OpenSpec change 时考虑补 1-2 个。

## 关键不变量 (real-artifact-test-mandatory 2026-05-20)

2026-05-20 一晚撞了 3 个同样模式的 bug（ru_maxrss / instrumentation
wiring gap / encounter eviction tick-semantic 错配）。每次都是：
**单元测试全过、API 契约 pass，但真 worker 跑起来死/废数据**。

根因：每个 module 的 unit test 只 mock 关键测量值或假设值，从来
没人写一个 test **真跑 worker + 读真 artifact + 断言 product invariant**。
caller-callee 之间的语义错配（e.g. tick_in_day vs tick_global）
要到 integration 才暴露，单测全 pass 的代码里能藏完整的语义 bug。

**强制不变量**（写新 capability / 改 caller 行为时 SHALL 遵守）：

1. **每个新 OpenSpec change SHALL 至少有 1 个 e2e integration test**
   真跑 dev smoke（subprocess 启动 `run_variant_suite.py`）+ 读真
   artifact 文件（snapshot.json / events.jsonl / memstat.jsonl）+
   断言 product-level invariant（不是 API contract）。
2. **禁止 mock 关键测量值**：psutil.memory_info、resource.getrusage、
   time.monotonic、文件 I/O 这些底层测量在 e2e test 里必须真实。
3. **测试要断言"东西在该在的地方"**，不只断言"函数被调用过":
   - 不只测 `emit_event` 被调用 → 测 events.jsonl 里有那条 line
   - 不只测 evict 返回值 → 测 snapshot 里 encounter 数量 > 0
   - 不只测 RSS cap "if 触发"机制 → 测 ru_maxrss/psutil 读到真值
4. **caller-callee 语义对齐 test**: 当 A 模块 call B 模块、传一个
   数值时，**verify A 传的数值语义符合 B 的假设**。e.g. tick 字段：
   写真测试 inject A 实际写的 tick 值给 B，看 B 行为符合预期。

**抓 bug 工作流**:

发现一个 bug → **先写抓得到这个 bug 的 test → 然后才修**。永远不
"fix and add test later"。今天 3 个 bug 复盘全部因为这个 — 修 bug
时只改 impl 不加 e2e test，下次撞到同样模式只能再撞一次才知道。

**触发条件**:

- 每次开新 OpenSpec change 时，design.md SHALL 显式列出"如何 e2e
  验证 product invariant 不只是 API contract"
- 每次发现 bug 写 backlog 时，**SHALL 列出"如果有 e2e test 早抓到，
  这个 test 应该长什么样"**
- 长期：把 `tools/preflight_publishable_spawn.py`（backlog 1.15）
  内嵌一个 5-second dev smoke e2e gate，每次 publishable spawn
  之前自动跑一遍

## 正式 publishable cell spawn 步骤 (2026-05-20)

每次 spawn publishable worker 跑实 LLM 之前，**4 个观察通道全部开启**
才算"开始观测"。监控不全 = 等于盲跑（2026-05-20 凌晨实测教训：
缺埋点情况下 worker 死掉只能事后从日志推断）。

### 1. Worker 主进程（detached）

```bash
SUITE=data/experiments/<run_dir>
OUT=$SUITE/variant_<v>
nohup env \
  RESILIENCE_TRUST_LAST_PREFLIGHT=1 \
  RESILIENCE_SNAPSHOT_EVERY_TICKS=12 \
  RESILIENCE_WAL_ENABLED=true \
  RSS_RESTART_MB=10000 \
  GC_EVERY_N_TICKS=200 \
  RSS_CHECK_EVERY_N_TICKS=50 \
  MEMORY_EVENT_EVICT_GRACE_DAYS=2 \
  SNAPSHOT_PRUNE_BEFORE_WRITE=1 \
  INSTRUMENTATION_OUTPUT_DIR=$OUT \
  INSTRUMENTATION_SEED=<N> \
  INSTRUMENTATION_SAMPLE_EVERY_N_TICKS=12 \
  LLM_SAMPLE_RATE=0.01 \
  LLM_RECORD_ERRORS_ALL=true \
  .venv/bin/python3 tools/run_variant_suite.py \
    --variants <v> --seeds 1 --seed-start <N> \
    --num-days 14 --agents 1000 --num-protagonists 500 \
    --mode publishable --use-aitown --aitown-provider deepseek \
    --workers 1 --suite-dir $SUITE \
    --resume --resume-strategy auto \
  >> $SUITE/worker_<v>.log 2>&1 &
WORKER_PID=$!
disown
```

### 2-5. 必须并行开 **4 个** 观察通道（每一次 spawn 都要，零妥协）

**为什么 4 个**：每个通道看不同维度的状态，任一缺失等于盲跑。
2026-05-20 凌晨教训：第一次 spawn 时 monitor 通道（audit_run_health）
忘了起，结果 worker 死掉只能事后从日志推。

| # | 用途 | 命令 | 输出 |
|---|---|---|---|
| **2** | **每 30s RSS / WAL / 文件大小 TSV**（轻量 bash probe，最低层量化数据）| `nohup bash <probe.sh> &` | `/tmp/swt-cell-probe-v3.tsv` |
| **3** | **memstat.jsonl rolling stats**（worker 进入 tick loop 后每 12 tick 一条 sample）| `nohup python tools/tail_memstat.py $SUITE <v> <N> --every 60 &` | `/tmp/swt-v3-tail-memstat.log` |
| **4** | **整 cell Markdown 概要**（events.jsonl + llm.jsonl 汇总 + 健康警告）| `nohup python tools/summarize_run_observability.py $SUITE <N> --variants <v> --watch 120 &` | `/tmp/swt-v3-summarize.log` |
| **5** | **进程健康监控**（process state / log silence / CLOSE_WAIT — `monitor-as-control-plane` 不变量的 "观察 + 报告" 角色）| `nohup python tools/audit_run_health.py $SUITE --watch 60 &` | `/tmp/swt-v3-audit-health.log` |

`tail -f /tmp/swt-v3-*.log` 实时看。

**spawn 完之后立刻确认 4 个 observer PID 都在**：
```bash
ps -p <probe_pid> <tail_memstat_pid> <summarize_pid> <audit_health_pid>
```

任一不在 → 重启那一个，不要继续，否则 spawn 时间废了。

### 5. 跑前清单（确认条件）

- [ ] `audit_resume_strategies.py` 确认 cell state + 选对
  `--resume-strategy`（特别注意 `INTERRUPTED_PARTIAL_MISSING` 必须
  `snapshot-only`）
- [ ] 无残留 worker（`ps aux | grep run_variant_suite`）
- [ ] LaunchAgent 状态符合预期（`launchctl list | grep swt`）
- [ ] 磁盘 > 30GB free（snapshot + JSONL 输出会占）
- [ ] memory_pressure / swap 状态健康（spawn 时如果已经 swap heavy
  就不要 spawn）

### 6. 检查节点（cache window 间隔）

每 5 min check **4 个数据源**，看的是：
1. **probe TSV** 里 RSS 趋势 + memstat / events 行数 + 最近 phase
2. **memstat.jsonl**（via tail_memstat）—— tick loop 进入信号 + RSS / CPU
   per-sample 真实值
3. **events.jsonl**（via summarize）—— PHASE 顺序 +
   SNAPSHOT_WRITE.events_evicted_before_write（验证 prune 生效）+
   EVICT 释放量
4. **audit_run_health**（process state / log silence / CLOSE_WAIT）——
   "worker 是否真活着、有没有死锁、socket 资源是否健康"

`tail -f /tmp/swt-v3-*.log` 同时看 4 个。

异常：
- WAL age 持续上涨且 log 不动 → stale / deadlock
- RSS 单调上涨没下降趋势 → cold-prune 没生效
- `all 8 keys open` 出现 → 网络层 cascade，检查 retry events

## 关键不变量 (snapshot-pre-write-prune 2026-05-20)

2026-05-20 复盘发现："3 个 RAM 优化全在 tick loop 内触发，覆盖不到
worker 启动期 snapshot 反序列化 35GB 峰值" — 这个峰值的根源是
snapshot 文件本身太大（6GB）+ Python JSON 反序列化 5-10× 膨胀。

snapshot 大的原因：`memory_store_state` 含 6M+ 个 encounter events
（93.5% of bytes），其中 99% 是 day < (current-2) 的冷数据。这些 events
按 cold-prune grace 本来就该被 evict，**只是 evict 只在 day_end 触发，
没在 snapshot write 之前触发**。

**修复已落地**（`prune-before-snapshot-write` 2026-05-20）：

- `MultiDayRunner._write_snapshot` 在 `SimulationCheckpoint.write_atomic()`
  **前**调用 `evict_cold_encounter_events_across_agents(before_tick=
  max(0, day_index - grace) * ticks_per_day)`，与 day_end eviction 共享
  既有 `MEMORY_EVENT_EVICT_GRACE_DAYS=2` 配置
- 早期 day（day_index < grace）时 cutoff <= 0 自动跳过
- evict 失败 SHALL log warning 但 SHALL NOT 阻塞 snapshot write
- env `SNAPSHOT_PRUNE_BEFORE_WRITE=0` 可一键关闭（诊断 / 旧格式回放）
- SNAPSHOT_WRITE event 新增 `events_evicted_before_write` 字段反映本次
  prune 释放的事件数，便于 post-mortem 直接看到优化效果

**实测效果**（50 agent × 3 day dev smoke, grace=0）:
- snapshot ON: 17.6 MB
- snapshot OFF: 25.2 MB
- 30% size reduction + 22% wall time reduction

至 publishable 1000 agent × 14 day 规模，预计 6GB → 600MB（90% reduction），
下次 resume 反序列化峰值 35GB → 3-6GB，**远低于 10GB RSS cap**。

## 关键不变量 (runtime-instrumentation 2026-05-20)

2026-05-20 凌晨实测 publishable resume 暴露 `_self_rss_mb()` 使用
`ru_maxrss` (生命周期峰值) 而非当前 RSS 的 bug — worker 一次 snapshot
反序列化 35GB 峰值后，RSS cap 永久 trip 形成重启死循环。同时所有埋点
集中在 tick-loop 后期，覆盖不到 setup / snapshot load / LLM 路径 /
eviction 实际效果。

**修复已落地**（`comprehensive-runtime-instrumentation` 2026-05-20）：

- `_self_rss_mb` → `_current_rss_mb`，**用 psutil.Process().memory_info().rss
  当前 RSS**，`ru_maxrss` 仅作 fallback + warning
- 新模块 `synthetic_socio_wind_tunnel/observability/instrumentation.py`
  提供 `RuntimeInstrumentation` process singleton
- 每 cell 写 **3 个独立 JSONL 文件**到 `INSTRUMENTATION_OUTPUT_DIR`：
  - `seed_<N>.memstat.jsonl` — 每 N tick 一条 (memory / CPU /
    gc / memory_store / dialogue / llm_health / handler timing)
  - `seed_<N>.events.jsonl` — 离散事件 (PHASE / EVICT / RETRY /
    SNAPSHOT_WRITE / EXIT) 100% 记录
  - `seed_<N>.llm.jsonl` — per LLM call (success 默认 sample 1%，
    error 100% 记)
- **9 个 phase 边界**: PROCESS_START → SETUP_START/DONE →
  SNAPSHOT_LOAD_START/DONE → TICK_LOOP_START → DAY_START/END → EXIT
- 关键环境变量：
  - `INSTRUMENTATION_DISABLE=1` → 完全关闭 (生产救火)
  - `INSTRUMENTATION_OUTPUT_DIR` → JSONL 输出目录
  - `INSTRUMENTATION_SAMPLE_EVERY_N_TICKS=12` (memstat 采样间隔)
  - `LLM_SAMPLE_RATE=0.01` (LLM 成功调用采样率)
  - `LLM_RECORD_ERRORS_ALL=true` (错误 100% 记录)

测试盲点修复：之前 17 个 RSS cap test 全部 mock RSS 值测"机制"，
新加的 `test_rss_mb_uses_psutil_current_not_ru_maxrss` 用真实 mmap
500MB → close 验证 current RSS 必然 drop 而 peak 单调，**捕获实际
ru_maxrss bug**。

埋点 SHALL NEVER crash worker — 每个 emit/sample 都 try/except 兜底。

## 关键不变量 (harden-worker-resilience 2026-05-19)

下面 3 条不变量（`monitor-as-control-plane` / `sigusr1-graceful-stop-corruption`
/ `memory-auto-restart`）+ `snapshot-resume-ram-peak` + atomic-write 多进程
安全 + setup-phase 哨兵 + DialogueService rolling cleanup + 直接 LLM call
asyncio.wait_for 兜底 — 全部 formalized 在 OpenSpec change
`harden-worker-resilience` 的 spec deltas (`run-resilience` +
`tick-level-resume` capability)。

Regression tests:
- `tests/test_harden_invariants.py` — 3 条不变量的源码级 / 行为级 guard
- `tests/test_direct_llm_timeout_guard.py` — 5 个直接 LLM call 位点的 wait_for guard
- `tests/test_aborted_in_setup_sentinel.py` — setup-phase 哨兵 4 test
- `tests/test_dialogue_service_eviction.py` — DialogueService rolling evict 8 test
- `tests/test_simulation_checkpoint.py::test_concurrent_writes_no_corruption` — 多进程 atomic write 10 轮 barrier 测试

## 关键不变量（memory-auto-restart 2026-05-19，backlog 1.7 B+F 已落地）

- **每 worker RSS 永封顶 `RSS_RESTART_MB` MB**——
  `synthetic_socio_wind_tunnel/orchestrator/multi_day.py::_init_memory_management_hooks`
  每 `RSS_CHECK_EVERY_N_TICKS` tick 检查 self RSS，超阈值 → 设置
  `_graceful_stop_requested=True` → 现有 graceful-stop 路径写 per-day
  partial + 退出 0 → `tools/resume_publishable.py` / LaunchAgent 下次 tick
  自动 spawn 替代（fresh RSS）
- **每 worker 周期性 gc.collect()**——同一 hook 每 `GC_EVERY_N_TICKS` tick
  跑一次，破 Python ref-cycle，省 100-300 MB / worker / 14 day
- 关键环境变量（默认值见代码）：
  - `RSS_RESTART_MB=0` (off) → 建议 publishable 设 `2500`（2.5 GB 单 worker 上限）
  - `GC_EVERY_N_TICKS=200` (~每 50 min 一次 gc.collect)
  - `RSS_CHECK_EVERY_N_TICKS=50` (~每 12 min 量一次 RSS)
- **依赖链**：B（RSS auto-restart）依赖 [[sigusr1-graceful-stop-corruption]]
  修复（不修，B 每次自杀都会污染数据）；今天两个一起修了
- backlog `docs/backlog.md` 1.7 的 B + F 已完成；C/A/D/E/H 未实施

## 关键不变量（snapshot-resume-ram-peak + spawn-burst-self-DDoS 2026-05-19）

> **2026-05-19 23:00+ 二次取证更新**：原本只记 RAM 视角，这次发现**同一 root
> cause 还引发 LLM API burst self-DDoS**——D2 attempt 6 (12:08:22) 4 worker
> 同时 spawn → 4 × 500 protag × 1 LLM/tick = ~2000 个并发 HTTP POST 一秒打
> DeepSeek → server-side 防 burst → silent TCP drop → `openai.APIConnectionError`
> → 8 keys cooldown → `FallbackBudgetExceeded` 自杀。**已在代码强制 staggered
> spawn**（见 `stagger-worker-spawn` change，2026-05-19 archived）。

- **同时 spawn N 个 worker 全部从 mid/late-run snapshot resume 同时**触发**两个**
  failure mode：
  - **(A) RAM 峰值**：4 worker × 3.5GB snapshot deserialize × Python 5-10× 膨胀
    = peak 50-100GB Python state，48GB RAM + 16GB swap 撑不住
  - **(B) LLM API burst self-DDoS**：4 × 500 protag agents × 1 LLM/tick =
    ~2000 个 HTTP POST 一秒打 api.deepseek.com → server-side 防 burst →
    silent TCP drop → 8 keys cooldown → worker 自杀
- **修复已在代码强制（不再是约定式）**：`tools/resume_publishable.py::
  _spawn_allowed_now()` 默认 `min_spacing_secs=300` (5 min)，`tools/
  run_variant_suite.py::_staggered_submit()` ThreadPool 路径也强制相同 spacing。
  env override：`RESILIENCE_MIN_SPAWN_SPACING_SECS` (0=disable for ad-hoc tests)
- last-spawn timestamp 持久化在 `~/Library/Logs/swt-resume-watchdog-last-spawn.json`
  （epoch + ISO + cell info，atomic write via tempfile+rename）
- 多 INTERRUPTED cell 在单个 LaunchAgent 周期内最多 spawn 1 个，剩余 cell
  `action="deferred_due_to_stagger"`，下个 5-min LaunchAgent fire 重新评估
- **原 RAM 视角的救命方案仍然有效**（万一守不住 spacing guard）：human via
  monitor SIGKILL 最 lagging 的那个 → swap 立刻从 18.1 GB 降到 5.0 GB → 其他
  worker 恢复 RUNNING_FRESH
- 入门指南：本文件 + `tools/resume_publishable.py` 顶部 docstring +
  `openspec/changes/archive/2026-05-19-stagger-worker-spawn/`

## 关键不变量（sigusr1-graceful-stop-corruption 2026-05-19）

- **不要对 mid-resume / mid-setup worker 发 SIGUSR1**——`run_variant_suite.py`
  的 SIGUSR1 handler ("跑完当前 tick → 写 partial → 退出 0") 在 worker 还没进
  tick 循环时被触发，会写一个 **`total_ticks=0` + `per_day_summaries=[]` +
  `graceful_stop=true` 的假 `seed_N.json`**，同时跑 **`cleanup_partials`** 删
  掉所有 `seed_N_day*.partial.json` —— 假 final + 没 partial fallback，cell 看
  起来像 DONE，实际上数据被污染
- D2 attempt 6 教训（2026-05-19 11:59）：误判 staleness → SIGUSR1 → 2068 写假
  `seed_42.json`（hyperlocal cell）+ 删掉 day0–day8 partial；幸好 snapshot 没
  被动，quarantine 假 final 后能从 snapshot tick2784 resume
- 防护：
  - `tools/resume_publishable.py` 已剥光 SIGUSR1 路径（[[monitor-as-control-plane]]）
  - human 需要 kill worker 时优先用 SIGKILL；SIGTERM 也会触发 graceful_stop
    handler 一样写假 final + 删 partial
  - 真要 graceful stop（让 worker 自己 flush + 退）只有跑了多个完整 day 的
    worker 才安全——发前先 grep 该 cell 的 `seed_N_day*.partial.json` ≥ 几个
- **修复已落地（2026-05-19）**：`tools/run_variant_suite.py:1704-1750` 在
  `result.metadata.graceful_stop=True` 时**完全跳过** `seed_N.json` 写、
  `seed_N_positions.json` 写、`DayCheckpointWriter.cleanup_partials`。
  graceful-stop 路径只保留 per-day partials + WAL + snapshot，下次 resume
  从这些 artifacts 走，audit 看不到 seed_N.json 知道 cell 还没完成

## 关键不变量（monitor-as-control-plane 2026-05-19）

- **守护 / watchdog / LaunchAgent / cron / 任何自动化运维脚本 SHALL NOT 持有
  termination 决策权**——它们只能观察状态、写日志、emit JSON event、做
  constructive recovery（spawn 死掉的进程、重启 crashed 服务）；SIGUSR1 /
  SIGTERM / SIGKILL / disable service / 删数据 / rollback config 等破坏性
  动作归 monitor / human（via monitor）
- D2 attempt 6 教训（2026-05-19 12:00）：`tools/resume_publishable.py` 把
  WAL staleness 判定直接绑了 SIGUSR1 动作。Mac 06:09 自动更新重启后，11:54
  spawn 的 4 个 worker 还在 load 3.5GB snapshot 没写 WAL，WAL mtime 还是
  pre-reboot 老时间→脚本误判 stale→12 分钟内 SIGUSR1 全部 4 个 worker，
  破坏 30GB RAM / 6 分钟 setup 工作
- 适用范围：`tools/watchdog_wal_deadlock.py`、`tools/audit_run_health.py`
  的 auto-remediate 部分、`tools/resume_publishable.py`、未来任何
  LaunchAgent / cron job
- 写新 daemon 时的合规清单：
  - ✓ Spawn missing workers / 重启 crashed 服务（idempotent + 可逆 OK）
  - ✓ 把 detected state 详细 emit 到 stdout / structured log
  - ✗ 不主动 kill / signal 任何已存活进程
  - ✗ 不删数据 / 不改配置 / 不 rollback
  - 真要 kill 时让 human 看 monitor 报告后手动触发，或暴露 explicit
    `--allow-terminate` flag（user-triggered + auditable）

## 关键不变量（setup-content-cache 2026-05-16）

- publishable run（β=4 seed scale）SHALL 先跑 `tools/prewarm_setup_content.py`
  让 per-seed 缓存 (`data/setup_content_cache/seed_<N>.json`) 落地——不能直接
  起 suite 然后让 setup phase 在线生成 500 protag × 2（life_history +
  identity_text）的 LLM call 突发，D2 attempt 3 (2026-05-16) 因此爆出
  0/500 life_history success
- `data/setup_content_cache/` 不进 git——每台机器独立 prewarm
- schema_version 升级（`_CURRENT_SCHEMA_VERSION` 在 `setup_cache.py`）SHALL
  重新跑 prewarm，旧 cache 自动 invalidate
- `tools/run_variant_suite.py` SHALL 通过 `_load_or_generate_setup_content`
  优先读 cache（HIT 路径 0 LLM call）；worker log 里 `[setup_cache] HIT for
  seed=N` 表示走的是 cache
- 详见 `docs/agent_system/17-setup-content-cache.md`

## 关键不变量（tick-level-resume 2026-05-16）

- **任何长跑（publishable）SHALL 启用 snapshot + WAL**——默认
  `RESILIENCE_SNAPSHOT_EVERY_TICKS=24`（hourly）+ `RESILIENCE_WAL_ENABLED=true`；
  最坏中断损失 ≤ `every_ticks × tick_minutes` simulated time（~2h）
- **新增子系统 mutable state 字段时必须 update `to_snapshot_state` /
  `from_snapshot_state`** —— 否则 resume 静默漏字段、跑出错误结果。round-trip
  测试是验证门
- **`--resume-strategy=auto` 默认**——snapshot 优先 fallback partial；
  `snapshot-only` 用于严格 resume；`partial-only` 走 run-resilience 旧路径；
  `none` 强制重头
- **`audit_run_health.py` 多了 `suspected_stuck`**——WAL mtime > 30× 期望
  tick 时长 → 标 deadlock；与 close_wait / 静默 log 一起判定 overall
- 入门指南：`docs/agent_system/16-tick-level-resume.md`

## 关键不变量（run-resilience 2026-05-15）

- **publishable run (1000 agent × 14 day) SHALL 先过 preflight gate**——
  `tools/preflight_full_smoke.py` 1000 agent × 1 day × 4 variant × 1 seed
  必须返回 0 才进入正式 publishable；`--skip-preflight` 在 publishable
  模式下被忽略（D1' 教训：scale-only bug 只在 1000 agent 才出现）
- **所有 real-provider tier client SHALL 用 `max_keepalive_connections=0`**——
  Gemini / DeepSeek / Anthropic 三家的内部 httpx 都必须显式注入这个限制，
  阻断 D1' CLOSE_WAIT 累积路径；任何长跑前用
  `tools/audit_run_health.py` 巡检 process_state + log silence + CLOSE_WAIT
- **任何长跑 worker SHALL 注册 `HotfixSignalHandler`**——`kill -USR1 <pid>`
  优雅停机协议：跑完当前 tick → 写 per-day partial → 退出 0；改 RESILIENCE_*
  环境变量后 `--resume` 续跑即新配置生效（不必改代码）
- **MultiDayRunner SHALL 在 on_day_end 写 `seed_{N}_day{D}.partial.json`**——
  最坏损失 ≤ 1 模拟天；整 variant 完成后 partial 由 `cleanup_partials` 清除
- 入门指南：`docs/agent_system/15-run-resilience.md`

## 关键不变量（fix-population-uses-typed-locations 2026-05-12）

- **agent.home_location SHALL 是 `building_type == "residential"` 的 building id**——
  不可以是 outdoor street segment（旧 bug：`_pick_connected_destinations` 只从
  outdoor 单池采样，导致 14 天 dwell 93% 在街上、0% 在 residential）
- agent 居住 / 工作 / POI 三池 SHALL 用 `build_location_pools(atlas, ...)` 构造，
  返回 `LocationPools(home_pool, work_pool, poi_pool, target_location)`，
  通过 `validate(atlas)` 校验三池 disjoint + 同一连通分量
- variant push `target_location` SHALL 来自 poi_pool（community / cafe / park），
  不再是 outdoor street
- dwell acceptance（baseline run）：residential ≥ 40% / street ≤ 20%；
  违反 `tools/audit_dwell_distribution.py` 即报警

## 对外报告与产出物的叙述风格（严格遵守）

参考样板：`docs/项目产出物.html`。任何"对外解释项目"的文档（产出物说明 / progress
report / pitch / 五幕报告 / 给非研发受众的总结）SHALL 按以下风格写：

1. **从日常生活场景切入，不从技术名词切入**。例：用"你认识楼上邻居吗"开头，
   而非"研究 attention-induced nearby blindness"。
2. **主线叙述里禁用技术黑话**——把 hyperlocal_push / encounter density /
   trajectory_deviation_m / variant 这类词翻译成"超在地推送"/"偶遇频率"/
   "走路路线"/"对照组"等中文白话，技术名作为副标题或脚注出现。
3. **每个产出物 / 章节用三段固定结构**：
   - **是什么**：白话描述 + 简短技术注脚
   - **解决什么问题**：用引号引一句"读者会问的问题"
   - **意义**：为什么没了它项目就不完整 / 这块在整个研究里的位置
4. **对照实验组用日常语言重命名**：
   - baseline → "对照组：什么都不推"
   - hyperlocal_push → "实验组（核心）：超在地推送"
   - global_distraction → "镜像组：推全球新闻"
   - phone_friction → "反技术组：减少手机吸引力"
5. **用真实城市名 / 街道名 / 数字让读者落地**——例如"Cowper 街口附近的偶遇密度
   从冷蓝色变成了热橙色"，而不是"location_id=cowper_street_seg_1 的 encounter
   count 提升了"。
6. **用 pullquote / panel / card 等视觉模块强化关键句**，而不是依赖纯文字段落。
7. **不要把"做了什么"和"为什么有意义"混在一起讲**——把现象、假设、方法、产出
   分章拆开，每章一个核心问题。

样板 HTML 的 6 大产出物白话名（之后的报告复用）：

| 技术名 | 对外白话名 |
|---|---|
| 实验证据 / contest.json | **实验答案** |
| 五幕报告 | **研究故事** |
| 可视化 HTML | **地图与图表** |
| 模拟系统代码 | **可运行的虚拟城市** |
| 复现性 lock | **可验证的研究记录** |
| 文档体系 | **研究知识库** |

## Project Overview

Synthetic Socio Wind Tunnel 是一个 AI 多智能体城市社会推演系统，研究 **Attention-induced Nearby Blindness**（注意力位移造成的附近性盲区）——手机注意力如何在高密度城市制造物理社区的"看不见的邻居"，以及超在地性反向推送能否把注意力、进而把人带回"附近"。

主边界是 `attention-main`；其余三层（`algorithmic-input` / `spatial-output` / `social-downstream`）是机制链上的上下游位置，而非平列边界。Canonical thesis 见 `docs/agent_system/00-thesis.md`，是所有 Phase 2 change 的 `Chain-Position` 门禁来源。

实验哲学与实验设计规格见 `docs/agent_system/13-research-design.md`（rival hypothesis framing / 14 天协议 / β 严谨度 / Hybrid 伦理 / 五幕报告结构），正式契约在 `openspec/specs/experimental-design/spec.md`。

技术上采用 CQRS（命令查询职责分离）架构，核心理念是"剧组模型"——将静态布景（Atlas）与动态道具状态（Ledger）分离。

## Project Structure

```
synthetic_socio_wind_tunnel/
├── synthetic_socio_wind_tunnel/              # 核心模块
│   ├── __init__.py          # 公共 API 导出
│   ├── core/                # 共享类型 (Coord, Polygon)
│   ├── atlas/               # 🎭 静态地图 (只读)
│   │   ├── models.py        # Region, Building, Room, DoorDef, ContainerDef
│   │   └── service.py       # Atlas 查询服务
│   ├── ledger/              # 📋 动态状态 (读写)
│   │   ├── models.py        # EntityState, ItemState, DoorState, EvidenceBlueprint
│   │   └── service.py       # Ledger CRUD
│   ├── engine/              # ⚙️ 写操作
│   │   ├── simulation.py    # SimulationService (移动、开门)
│   │   ├── collapse.py      # CollapseService (薛定谔细节生成)
│   │   └── navigation.py    # NavigationService (路径规划)
│   ├── perception/          # 📷 读操作
│   │   ├── models.py        # ObserverContext, SubjectiveView
│   │   ├── pipeline.py      # PerceptionPipeline
│   │   ├── exploration.py   # ExplorationService (认知地图)
│   │   └── filters/         # 环境、听觉、嗅觉、技能滤镜
│   └── cartography/         # 🗺️ 地图构建 (离线)
│       ├── importer.py      # GeoJSON 导入
│       └── builder.py       # 编程式构建
├── tests/                   # 测试代码
└── docs/                    # 设计文档
```

## Commands

```bash
# 安装依赖
pip install -e ".[dev]"      # 开发环境
pip install -e ".[full]"     # 完整功能 (LLM + Web)

# 运行测试
python -m pytest tests/ -v

# 验证导入
python -c "from synthetic_socio_wind_tunnel import *; print('All imports OK')"

```

## Architecture Concepts

### CQRS 分离
- **Atlas (布景组)**: 只读静态地图，定义墙、门、容器
- **Ledger (道具组)**: 读写动态状态，管理位置、物品、证据

### 核心服务
- **SimulationService**: 写操作（移动、开门、发现线索）
- **CollapseService**: 薛定谔细节生成（首次检查时生成内容）
- **PerceptionPipeline**: 读操作（主观视角渲染）
- **ExplorationService**: 认知地图（角色探索记录）
- **NavigationService**: 路径规划（门感知路由）

### 关键特性
- **空间预算系统**: 容器有容量限制
- **证据蓝图系统**: 剧情必需证据保证出现
- **罗生门效应**: 同一场景不同角色看到不同内容
- **多模态感知**: 视觉、听觉、嗅觉

## Key Files for Modifications

- `synthetic_socio_wind_tunnel/engine/simulation.py` - 移动和交互逻辑
- `synthetic_socio_wind_tunnel/engine/collapse.py` - 细节生成逻辑
- `synthetic_socio_wind_tunnel/perception/pipeline.py` - 感知渲染
- `synthetic_socio_wind_tunnel/perception/filters/` - 添加新滤镜
- `synthetic_socio_wind_tunnel/atlas/models.py` - 静态数据模型
- `synthetic_socio_wind_tunnel/ledger/models.py` - 动态数据模型

## Documentation

- `docs/项目Brief.md` - 项目总体方案、理论框架、三大实验设计
- `docs/agent_system/` - Agent 系统架构设计（01~06）
- `docs/map_pipeline/` - 地图构建方案（OSM 导入 + 编程式构建）
- `docs/WIP-progress-report.md` - 当前进度汇报

## Testing

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/test_atlas.py -v
python -m pytest tests/test_ledger.py -v
python -m pytest tests/test_perception.py -v
python -m pytest tests/test_cartography.py -v
python -m pytest tests/test_agent_phase1.py -v
```
