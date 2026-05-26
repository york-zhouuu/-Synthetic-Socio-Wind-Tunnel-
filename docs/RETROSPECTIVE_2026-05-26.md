# 项目复盘 + 需求盘点 · 2026-05-26

> 本文是一次性的横向梳理 — 把 publishable run 5 月 12-25 日跑下来累计
> 暴露的项目问题、已 codify 的不变量、还没处理的痛点, 全部摊平到一个
> 索引里。 详细的不变量原文在 [CLAUDE.md](../CLAUDE.md), 详细 incident
> 在 [docs/sessions/](sessions/), 这里只做拓扑 + 未 close 项的 TODO list。

## TL;DR

publishable run 1000 agent × 14 day × 4 variant × N seed 这条管线累计
撞了 **3 类反复出现的故障模式 + 1 类工程文化问题**:

| 类别 | 具体表现 | 发现频次 | 已 codified |
|---|---|---|---|
| **资源边界** | RSS 累积 / snapshot 反序列化峰值 / asyncio handler hang | 5+ 次 | 部分 |
| **并发自伤** | 错峰 spawn / LLM API burst self-DDoS / 守护脚本主动 kill | 4 次 | 是 |
| **wiring gap 静默漂移** | `getattr(obj, "name", default)` 把字段重命名吞掉 | 4 次同晚 | 是 |
| **测试覆盖盲区** | unit test 全绿 / integration 失败 / 真 worker 报废 | 7 个产线事故 | 部分 |

外加 **publishing 侧** (portfolio 网站 + 对外文档) 几个独立教训, 跟仿真
管线无关但属于同一项目交付的一部分, 也一起记下。

---

## 1 · Worker 自我维持 (资源边界类)

**核心矛盾**: publishable run 单 worker 进程跑 14 天模拟 = wall-clock
4-6 小时 + 1000 agent × ~3000 encounter event/agent 持续累积。 即使
正常运行, RSS 也会单调上涨, 超过 ~8 GB 后系统开始 swap, kernel 把
进程踢飞。

**具体撞过的坑**:

- `_self_rss_mb()` 用了 `resource.getrusage().ru_maxrss` (**生命期峰值**,
  不是当前 RSS) — 一次 snapshot 反序列化峰值 35 GB 之后, ru_maxrss
  永久 trip RSS cap, worker 进入"重启-load snapshot-再 trip"死循环。
  → 修: `psutil.Process().memory_info().rss` 当前值; 详见
  [`runtime-instrumentation` 不变量](../CLAUDE.md#关键不变量-runtime-instrumentation-2026-05-20)
- snapshot 文件本身 6 GB (93.5% 是 cold encounter events), 反序列化
  Python state 35 GB。 → 修: `SNAPSHOT_PRUNE_BEFORE_WRITE=1` 在写 snapshot
  前先 evict cold events, 6 GB → 600 MB / 90% reduction; 详见
  [`snapshot-pre-write-prune`](../CLAUDE.md#关键不变量-snapshot-pre-write-prune-2026-05-20)
- DialogueService `_dialogues` dict 14 天 unbounded 累积 → rolling
  cleanup 落地 (`harden-worker-resilience` change)
- asyncio handler 单次 hang 25 分钟 (httpx read_timeout 默认 300s ×
  retry 3) → `OPERATION_POOL_HANDLER_TIMEOUT_SEC=90` +
  `RESILIENCE_POOL_READ_TIMEOUT=60` + `RESILIENCE_RETRY_MAX_ATTEMPTS=2`

**已落地** (backlog 1.7):
- B + F: RSS-based auto-restart + 周期性 `gc.collect()` (worker 自杀
  → resume 比让坏状态累积更便宜)
- C: cold memory event prune (`MEMORY_EVENT_EVICT_GRACE_DAYS=2`)
- 主动 `RSS_RESTART_MB=6000` (~2-3 小时自动 restart 刷新 asyncio 状态)

**未做**:
- backlog 1.7 A (进程间共享只读数据 via shared memory) — 高 ROI 但
  需要重构 launcher
- backlog 1.7 D (fork-based worker spawn) — 比 RSS_RESTART 更优雅
- backlog 1.14 (单 worker 多核并行化) — Python GIL 解锁, 见 docs/
  内 `hot-path-analysis-2026-05-19.md`

---

## 2 · 并发自伤 (多 worker 协调)

**核心矛盾**: 4 variant × 同时 spawn = 4 个 worker **同时** 触发 RAM
峰值 + **同时** 打满 LLM API 配额。 看起来跟单 worker 一样, 实际
**互相加压**。

**具体撞过的坑**:

- **RAM 峰值同步**: 4 worker × 3.5 GB snapshot deserialize × Python
  5-10× 膨胀 = peak **50-100 GB**。 48 GB RAM + 16 GB swap 撑不住,
  最 lagging 的 worker 被 OS 杀, 救活后还是同时 spawn 又同时撞。
- **LLM burst self-DDoS** (2026-05-19 attempt 6): 4 worker × 500
  protagonist × 1 LLM/tick = **~2000 个 HTTP POST 一秒** 打
  api.deepseek.com → server-side 防 burst → silent TCP drop →
  `openai.APIConnectionError` → 8 key 全 cooldown → fallback budget
  耗尽 → worker 自杀链式反应
- **重启又同时 spawn**: `resume_publishable.py` 看到 4 worker 全死,
  4 个一起 spawn → 又触发上面两条

**已落地** ([`stagger-worker-spawn`](../openspec/changes/archive/2026-05-19-stagger-worker-spawn/) change 已归档):
- 强制 `min_spacing_secs=300` (5 分钟) 错峰 spawn — 代码级强制, 不再
  是约定式
- `~/Library/Logs/swt-resume-watchdog-last-spawn.json` 持久化上次 spawn
  时间戳 (atomic write)
- 多 INTERRUPTED cell 一个 LaunchAgent 周期内最多 spawn 1 个

**未做**:
- LLM provider 客户端的 client-side burst smoothing (现在靠 stagger
  spawn 间接绕过, 没在 LLM 客户端做 rate limiting)

---

## 3 · 信号 / 控制平面边界

**核心矛盾**: 守护脚本 (watchdog, resume_publishable, LaunchAgent)
看到状态异常想"帮一把", 但**它持有 termination 决策权**就会出事。

**具体撞过的坑**:

- **SIGUSR1 mid-resume 写假 final** (2026-05-19): worker 还在 mid-setup
  load 3.5GB snapshot, WAL mtime 还是 pre-reboot 老时间 → watchdog 误判
  stale → SIGUSR1 → graceful-stop handler 写 `total_ticks=0` +
  `graceful_stop=true` 假 `seed_N.json`, 同时 `cleanup_partials` 删了
  全部 day-partial → cell 看起来 DONE 但数据废
- **守护脚本主动 SIGUSR1 跨过这个边界**: `resume_publishable.py` 把
  WAL staleness 判定**直接绑 SIGUSR1 动作**, 12 分钟内 SIGUSR1 全部 4
  worker, 破坏 30 GB RAM / 6 分钟 setup 工作

**已落地**:
- [`monitor-as-control-plane`](../CLAUDE.md#关键不变量monitor-as-control-plane-2026-05-19)
  不变量: 守护脚本**SHALL 只观察 + 报告 + spawn 死掉的进程**, 不主动
  kill / signal 已存活进程
- [`sigusr1-graceful-stop-corruption`](../CLAUDE.md#关键不变量sigusr1-graceful-stop-corruption-2026-05-19)
  不变量: `result.metadata.graceful_stop=True` 时**完全跳过** `seed_N.json`
  / cleanup_partials, 让 resume 走 per-day partial + WAL + snapshot
- WAL deadlock 自动救援单独写了 `tools/watchdog_wal_deadlock.py` (Plan
  B 加进了 5 个必备观察通道, 但**用户授权时才 escalate 到 SIGKILL**)

**未做**:
- WAL stale 判定的更鲁棒指标 (除 mtime 之外加 progress event 时间戳)
  以避免 mid-load false positive
- LaunchAgent 集成 audit log, 让所有 spawn / signal 动作都可追溯

---

## 4 · 字段重命名静默漂移 (wiring gap)

**核心矛盾**: 跨模块字段访问用 `getattr(obj, "field_name", default)`
当字段被重命名时**完全没有任何信号** — 既不抛错也不警告, 监控只是
"返回 default", 而 default 值跟"字段值=0"看起来一样, 走完整个 silent
failure 链。

**2026-05-20 一晚撞了 4 个同模式 bug**:

| Bug | 字段 | 模块 | 后果 |
|---|---|---|---|
| ru_maxrss 误用 | `ru_maxrss` vs `psutil.rss` | `_self_rss_mb` | RSS cap 永久 trip |
| phase event wiring gap | 9 个 PHASE event 名字 vs spec | MultiDayRunner | 监控盲跑 |
| encounter eviction tick semantic | `ev.tick` (per-day) vs `before_tick` (global) | `evict_cold_encounter_events` | 删光全部 encounter |
| dialogue counter wiring gap | `_active_dialogues` vs 真实 `_dialogues` | memstat instrumentation | 跑了 589 dialogue 但显示 0 |

**已落地** ([`real-artifact-test-mandatory`](../CLAUDE.md#关键不变量-real-artifact-test-mandatory-2026-05-20)):
- 跨模块字段访问 **prefer 直接属性** `obj.field` (AttributeError 是好事)
- 不得不用 getattr 兜底时 SHALL 加 startup-time assertion
- 监控字段的 unit test 必须 real-artifact (真造对象 / 真读 JSONL),
  不只 mock counter 值
- 重命名字段时 SHALL `git grep "_old_name"` 找所有 string-form
  reference (mypy/pyright 抓不到 string form)

**未做**:
- 全局 codebase audit 一遍所有 `getattr(x, "...", default)` 调用点,
  转成直接属性 + assert (估计 ~50 处, 1-2 小时工作量)

---

## 5 · 测试覆盖盲区

**核心矛盾**: pytest 全绿是**必要条件, 远不充分**。 项目过去 7 个产线
事故全部在测试全绿的代码里。

**8 类问题** (每类对应一个真实事故 case study, 详见
[`docs/testing-philosophy.md`](testing-philosophy.md)):

1. 中断路径测了吗 (SIGUSR1 / SIGTERM / cancel)
2. 启动期边界测了吗 (WAL mtime < proc start time)
3. 资源 budget 测了吗 (publishable-scale fixture RSS / 时长)
4. 外部依赖失败路径 mock 了吗 (subprocess / HTTP / DB 3+ failure mode)
5. 并发 / atomic race 测了吗 (threading.Barrier + 10 轮迭代)
6. long-running 数据结构有界性测了吗 (14 day 后 size < threshold)
7. smoke 覆盖最坏一天了吗 (day 11+ peak, 不只是 day 0)
8. 不变量配源码级 + 行为级双层 guard 了吗

**已落地** test 正例:
- `tests/test_harden_invariants.py` (3 不变量 × 2 层 = 6 tests)
- `tests/test_simulation_checkpoint.py::test_concurrent_writes_no_corruption`
  (10 轮 barrier 并发 race test)
- `tests/test_direct_llm_timeout_guard.py` (5 个直接 LLM call 位点的
  wait_for guard)
- `tests/test_instrumentation_dialogue_counter.py` (real-artifact 模式)

**未做** (CLAUDE.md 已列出待补 high-priority test):
- `test_concurrent_resume_ram_budget.py` (问题 3)
- `test_find_pid_ps_failure_modes.py` (问题 4)
- `test_dialogue_service_bounded_long_run.py` (问题 6)
- `test_smoke_publishable_day11.py` (问题 7)

**新 OpenSpec change 时 SHALL 满足的**:
- 至少 1 个 **e2e integration test** 真跑 dev smoke + 读真 artifact +
  断言 product-level invariant (不是 API contract)
- 禁止 mock 关键测量值 (psutil / resource / time.monotonic / 文件 I/O)
- 断言"东西在该在的地方", 不只断言"函数被调用过"
- caller-callee 语义对齐 test (verify A 传的数值符合 B 的假设)

---

## 6 · LLM provider 韧性

**核心矛盾**: openai SDK / anthropic SDK / google-genai SDK 各家
exception 类层级不同, 项目的 `RetryPolicy` 只列了 Python builtins
`(TimeoutError, ConnectionError, asyncio.TimeoutError)`, 错把厂家
specific exception **全部归类 "unknown"**, 零 retry → 单次网络 blip
直接 trigger key cooldown → 8 key 全 open → fallback budget 耗尽。

**实测**: `isinstance(openai.APIConnectionError(request=None), ConnectionError)`
返回 `False` (它的 MRO 是 `APIError → OpenAIError → Exception`, 不继承
Python builtin `ConnectionError` — 那个是 `OSError` 子类)。

**已落地** (`retry-network-blip-tolerance` change 已 propose, tasks 待
做):
- 加 `_RETRYABLE_EXC_CLASS_NAMES` frozenset 用 `type(exc).__name__`
  字符串匹配 — duck-typed 不硬 import 三家 SDK
- 覆盖 openai/anthropic 的 `APIConnectionError` / `APITimeoutError`,
  httpx 的 `ConnectError` / `ReadError` / `RemoteProtocolError` 全套
  timeout, google-genai 的 `DeadlineExceeded` / `ServiceUnavailable`

**未做**:
- 实现 `retry-network-blip-tolerance` change 的 tasks (proposal +
  design + spec delta 都写好了, 还没动代码 + test)
- backlog 1.9 (所有直接 LLM call 加 asyncio.wait_for 硬超时兜底) —
  这条已经落地了 5 个位点, 但 hot path 之外可能还漏

---

## 7 · 数据 hygiene + git

**核心矛盾**: 仿真产生海量 artifact (snapshot / WAL / events.jsonl /
memstat.jsonl / positions / 每天 partial), 单次 publishable run 数据
~3-6 GB; 14 天 + 多 variant + 多 seed 累积可达 **30+ GB**。 容易污染
git 历史。

**实测撞过的坑**:
- 2026-05-26 catchup commit 时发现 `data/experiments_archive_pre_2026_05_21/`
  **32 GB** 还没 gitignore — 准备 push 之前 catch 到, 加进 .gitignore
- `data/analysis/trajectory_cache_f1.json` **63 MB** 单文件超 GitHub
  50 MB 警告线, 也是 precompute cache 不该入仓
- `data/experiments/` 早就在 gitignore 但旧 publishable_v1/v2 还残留
  在 git 历史里 (148 个 D 记录就是清这些)

**已落地**:
- .gitignore 多层防线: `data/experiments/`, `data/runs/`, `data/setup_content_cache/`,
  `data/population_cache/`, `data/experiments_archive_*/`,
  `data/analysis/*_cache_*.json`, `releases/`, `seed_*.memstat.jsonl` 等
- runtime-instrumentation 默认输出到 `INSTRUMENTATION_OUTPUT_DIR` 不
  写仓库根

**未做**:
- `git lfs` 或者外部 artifact storage (S3 / R2) — 现在产出的 case study
  PDF / poster SVG 5-15 MB 已经在 git 里 OK, 但下次有更大的就 LFS
- 一个 `tools/check_git_hygiene.py` pre-commit hook, 阻止 >50 MB
  单文件 + 任何 `data/experiments*/` 路径意外入仓

---

## 8 · 数据分析口径一致性 (thesis-aligned)

**核心矛盾**: 项目 thesis 是 **attention-induced nearby blindness ·
附近性盲区** — 关心的是"物理在场但注意力不在", 不是"物理 proximity
总量"。 用错口径会导致 finding 跟 thesis 脱节, 数字方向甚至反过来。

**实测对比** (2026-05-24 之前几次报告踩过):
- 物理同框 (`distinct_pairs`): HP/PF vs BL 几乎一样 (1.04× / 1.10×) — 看
  起来"没差"
- noticed 口径 (`agent_events[kind=encounter] AND 'noticed' in tags`):
  HP/PF vs BL 翻 **2.3× / 2.6×**, 而且 94% 是 BL 没看见过的人 — 真正
  的 finding

**已落地** (CLAUDE.md 已写入强制规则):
- 所有数据分析 / 报告 / 案例研究 / 对外文档 SHALL 用 **noticed 口径**,
  NOT 物理同框 / 擦肩 口径
- 语言规则: **不用** "擦肩 / 偶遇", 用 **"看见 / 注意到 / 抬头看见 /
  noticed"**
- 正例 reference: `tools/case_studies/build_a0290_longform.py:73-74` +
  `tools/h17_h19_noticed_redo.py`

**未做**:
- backfill 一遍早期已发布的报告 (`docs/项目实验结果_v3.html` 之前的
  几个), 检查是否还混用 distinct_pairs

---

## 9 · 对外写作 / 文档约定

(这一节跟仿真管线无关, 是 publishing 侧的累积约定 — 但属于同一项目
交付)

**已落地约定** (CLAUDE.md):
- **Tier label vs 模型名**: 代码里 `Tier = Literal["sonnet", "haiku",
  "nano"]` 是历史包袱保留, 但**对外解释**时用真实模型名 + 选型理由
  ("DeepSeek v4-pro 多步推理需要顶档质量"), 不写 "走 sonnet-tier"
- **2.5D 视觉规范**: "2.5D" 一律指 `docs/poster_map_*.svg` 那套静态
  等距投影 SVG 风格, **不是** maplibre+deck.gl, **不是** matplotlib 3D
- **数据分析口径**: noticed 不擦肩 (见第 8 条)
- **对外报告 9 原则**:
  1. 假定读者完全不知道项目背景, 不用 BL/HP/GD/PF 缩写
  2. 给不懂项目的人读得懂 = 最后一道闸
  3. 工具/LLM/agent 的缺陷不能成为 finding
  4. 不写 caveat 自废 (除"all claims are comparative" 之外)
  5. 真 finding 是 comparative + counterintuitive
  6. 概念定义 SHALL web-search verify, 不准凭直觉编 etymology
  7. Finding 一个一个推进, 不批量生成
  8. 数字必须 verified, 不准编
  9. 假设跟数据不一致时跟数据走 reframe

**未做**:
- 一份针对**研究学术读者**的产出物 (现在 5 个 v4-v7 项目实验结果.html
  都偏 design researcher / general 读者, 没有 narrative for paper
  reviewer)

---

## 10 · Publishing 侧 (portfolio 网站) 教训

跟仿真无关但属于同一项目交付。 5 月 25-26 累计:

- **Vercel 生产 build 比 `next dev` 严格**: ESLint `react/no-unescaped-entities`
  + `@typescript-eslint/strict` + Zod schema/TS type 不一致 — `next dev`
  全 pass, `next build` 报 ~10 个 error / warning 让 build fail。 修法:
  本机 `pnpm run build` 是 push 前最后一道闸
- **GitHub-Vercel webhook 不 backfill**: reconnect 集成之后必须**重 push
  一个 commit** 才触发 build, 不会自动 deploy 历史 HEAD
- **drei `<Html>` click 在 R3F canvas 里不可靠**: `distanceFactor` 把
  hit area 缩到针眼大小, 移动端 / 触屏几乎点不动。 修法: 把可点击元素
  从 R3F 内挪到普通 DOM (SVG overlay + 屏幕投影定位)
- **`Nvw` clamps 在横屏手机上字超大撑爆 viewport**: 844×390 landscape
  phone 的 vw 仍然给 ~22px+ body 字, 不止行高超 100svh。 修法: 改
  `min(Nvw, Mvh)` 让 vh 来截
- **强制横屏 gate**: 现有 cinema 100svh + 16:9 scene layout 在竖屏
  手机彻底破碎。 修法: `<OrientationGate />` 检测 portrait + touch +
  <900px → 全屏覆盖, 必须旋转才能继续 (无 dismiss 选项)

**未做**:
- portfolio 项目自己也该有一个 e2e visual regression test (Playwright?
  Percy?) — 现在每次部署只本机 dev / 一次 build verify, 没固化"上次
  对就这样"的视觉契约
- portfolio 的 build size / first-load JS 优化 (现在 102 kB shared
  chunks 已经不错, 但 65 MB 静态 asset 移动 4G 加载慢)

---

## 11 · 横切观察 · 模式与下一步

### 反复出现的元模式

1. **静默漂移 > 显式爆炸**: 7 个产线事故里 5 个是 silent failure
   (字段返回 default / counter 显示 0 / 监控盲跑), 而不是 exception
   抛出。 → 设计原则: **prefer fail-loud**, AttributeError 是好事
2. **并发把单点风险放大 ×N**: 1 worker 看着没事的内存/网络/IO 模式,
   4 worker 同时跑就 ×4 倍同步打到同一资源。 → 设计原则: **错峰 +
   独立化** (per-worker 配额, 不共享 mutable state)
3. **测试模式跟产线模式不一致**: unit test 用 mock 跟 production code
   用 mock 假设一样 → 一起错都不被抓。 → 设计原则: **e2e real-artifact
   test 必须有 1 个**
4. **守护脚本边界蔓延**: 看到状态异常就想"帮一把", 但破坏性动作 (kill
   / 删数据 / rollback) 归 monitor / human, 不归自动化。 → 设计原则:
   **monitor-as-control-plane**

### 下一步排期建议

**高优** (publishable run 还可能再撞):
- [ ] backlog 1.9 hot-path 之外的 LLM call 也加 `asyncio.wait_for`
      硬超时兜底
- [ ] retry-network-blip-tolerance change 的 tasks 落地 (proposal 已
      写好)
- [ ] 全 codebase audit `getattr(x, "...", default)` → 直接属性 + assert
- [ ] CLAUDE.md 列的 4 个 high-priority test 补上

**中优** (不影响 publishable run 但能减重复劳动):
- [ ] backlog 1.7 A 进程间共享只读数据
- [ ] backlog 1.7 D fork-based worker spawn
- [ ] `tools/check_git_hygiene.py` pre-commit hook
- [ ] backfill 早期报告的数据分析口径 (noticed vs 同框)

**低优** (研究侧 nice-to-have):
- [ ] backlog 1.14 单 worker 多核并行化 (Numba JIT / ProcessPoolExecutor)
- [ ] DialogueService 持久化 (backlog 1.12)
- [ ] portfolio e2e visual regression test

### 持续投资点 (不是 task, 是文化)

- 每个 OpenSpec change 的 design.md SHALL 显式列**如何 e2e 验证
  product invariant 不只 API contract**
- 每个 bug 发现时 SHALL **先写抓得到这个 bug 的 test → 再修**
- 每次大 publishable spawn 前 SHALL **5 个观察通道全部 alive** 才算
  "开始观测"

---

## 索引 — 详细资料

- [CLAUDE.md](../CLAUDE.md) — 项目 memory + 14 条关键不变量原文
- [docs/backlog.md](backlog.md) — 已识别需求 1.1–1.14
- [docs/testing-philosophy.md](testing-philosophy.md) — 测试 8 类问题
  详细 case study
- [docs/sessions/](sessions/) — 时间序 incident note (2026-05-10 起)
- [docs/agent_system/15-run-resilience.md](agent_system/15-run-resilience.md) —
  run resilience capability 入门
- [docs/agent_system/16-tick-level-resume.md](agent_system/16-tick-level-resume.md) —
  tick-level resume capability 入门
- [docs/agent_system/17-setup-content-cache.md](agent_system/17-setup-content-cache.md) —
  setup content cache capability 入门
- [openspec/changes/](../openspec/changes/) — proposed/active spec changes
- [openspec/specs/](../openspec/specs/) — accepted capability specs

---

*本文 freeze on 2026-05-26 catchup commit (`c604dd6`); 后续新增 incident
请走 [docs/sessions/](sessions/) 新文件 + 必要时 CLAUDE.md 加新不变量,
不就地修改此文。*
