## Context

本项目截至 2026-05-19 在性能 / 内存 / 资源决策上**几乎全凭直觉**：
- backlog 1.7 (B+F) 的阈值 (RSS_RESTART_MB=2500, GC_EVERY_N_TICKS=200)
  从未量过 worker 真实 RSS 行为
- DialogueService rolling-cleanup 2-day grace 从未量过 dialogue
  retrieve 时间窗
- 上个 change `profile-publishable-hot-path` 只跑了 dev scale，
  publishable scale extrapolation 是插值

用户挑明这是猜。本 change 建立"量化能力"，让下一波优化拿数据说话。

## Goals / Non-Goals

**Goals:**
- 装齐 4 个 dev profiler 工具（memray / line_profiler / pyinstrument /
  psutil 显式 declare）
- DayRunSummary 加 6 个 observability 字段，每 publishable run 自动落
  hot-path 时间序列
- 3 个 git-tracked baseline fixture（memray summary / line_profile
  events_at_tick / RSS time-series）
- regression guard 防止"实现内偷偷退化"
- 严格 TDD：所有 schema test 和 mock test 先写（红），再实现 instrumentation

**Non-Goals:**
- 不优化任何 hot path（events_at_tick / dialogue grace 留下一个 change）
- 不跑 1000-agent publishable profile（14h 成本，留下个 change）
- 不引入 OpenTelemetry / distributed tracing
- 不集成 CI memory budget enforcement（先 manual diff）
- 不动 existing `hot-path-baseline` capability（complement 不 replace）

## Decisions

### 决策 1：DayRunSummary 加新字段而非用 sidecar 文件

**A（采纳）**：直接加进 `DayRunSummary`（向后兼容默认 0/None）。
**B**：用 sidecar file `seed_N_observability.json`。

选 A 因为：
- `llm_fallback_pct` 在上个 change 也走这条路径，一致
- aggregate.json / contest.json 自动拿到 observability 数据
- 旧 JSON 读取仍能加载（pydantic default=0），不破坏 resume

### 决策 2：memray 原始 .bin 不进 git，只 commit summary JSON

**A（采纳）**：.bin（5-20 MB）进 `.gitignore`；summary JSON（< 50 KB）git-track。
**B**：用 git-lfs 存 .bin。
**C**：完全跳 memray，只用 tracemalloc + objgraph。

选 A 因为：
- git-lfs 会增加 repo clone 复杂度，对一般 dev 来说 overkill
- summary JSON 足够 regression diff（top-30 allocator type + size）
- 真要看原始 .bin，dev 可以本地重新跑 memray

### 决策 3：line_profiler 用 @profile decorator vs 命令行 -m kernprof

**A（采纳）**：`@line_profiler.profile` decorator + runtime opt-in via
`LINE_PROFILER_ENABLE=1` env，避免 production code 永久带 decorator。
**B**：单独 fork `events_at_tick` 加 `@profile`，build 时 strip。

选 A 因为：
- decorator 默认 no-op（unless env set）
- production CI / publishable run 完全无 overhead
- dev 一行 env 就开

### 决策 4：psutil instrumentation 用 try/except 防止 crash

**A（采纳）**：psutil 调用包 try/except，失败 fallback 到 `-1` 或
`None`，log warning，**不让 run crash**。
**B**：psutil 失败 raise 出去，让 run 显式失败。

选 A 因为：
- observability 是 nice-to-have，不能让 production run 死于一个 metric
- macOS / Linux psutil API 偶尔有平台差异
- fault-injection test 显式覆盖这条路径（Layer 6）

### 决策 5：tick_latency 分布用 p50/p95/max 而非 mean

**A（采纳）**：p50 / p95 / max（3 个值）。
**B**：mean + stddev。

选 A 因为：
- tick latency 几乎肯定是 long-tail distribution（LLM call 偶发 slow）
- mean 被 outliers 主导；p95 / max 显示 worst-case
- 与可观测性社区惯例（SRE Golden Signals）一致

### 决策 6：RSS time-series 采样频率

**A（采纳）**：每 12 tick (~30 min sim time) 采样一次。
**B**：每 tick 一次。
**C**：每 day 一次（与 DayRunSummary 同步）。

选 A 因为：
- B 太密：psutil call 是 ~1 ms，每 tick 一次会引入 ~5% 开销在 dev smoke
- C 太疏：14 day 只有 14 个数据点，看不清增长曲线
- A 是 publishable run 一天 ~24 个数据点，曲线足够清晰，开销 <0.1%

## Risks / Trade-offs

- **[Risk] memray macOS 系统依赖** → 文档明确写 `brew install libunwind`，
  CI 上若 fail 加 skip-marker
- **[Risk] instrumentation 自身的 overhead 进了 hot path** → Layer 4
  budget test 显式 enforce <5%；mitigation：所有 instrumentation 在
  `on_day_end` 而非 `on_tick_end`，288× 频率差
- **[Risk] memray summary fixture 在不同机器上可能 top-N 顺序不稳** →
  regression test 只比较 top-3 **集合**（order-insensitive），与上个
  change 同模式
- **[Trade-off] 加 4 个 dev deps** → ROI 极高（量化能力作为后续所有
  优化决策的基础）；用户运行 production publishable 不需要装

## Migration Plan

1. 装 dev deps + 更新 `.gitignore`
2. TDD 红：schema + mock + budget + property + fault injection tests
3. 实现 instrumentation 进 `MultiDayRunner.on_day_end`
4. 跑 dev smoke 生成 3 个 baseline fixture
5. regression test 转绿
6. archive

**回滚**：纯加新字段 + 新 fixture + 新 tool；revert 一个 commit 即可，
production behavior 零影响。

## Open Questions

- memray 原始 .bin 真的不进 git 吗？若 reviewer 想看 sample，是否
  需要 git-lfs？**判读**：先不进，等下次有 reviewer 抱怨再加 LFS
- DayRunSummary 加 6 个字段后，**seed_N.json size 涨多少**？
  估计 + 14 day = 14 × ~200 字节 = 2.8 KB extra/seed，忽略不计
- publishable run 时 instrumentation 默认开吗？**判读**：默认开，因为
  这就是本 change 的核心价值——publishable 自带 hot-path 时间序列
