# 项目复盘 + 需求盘点 · 2026-05-26

> 本文是一次性的横向梳理 — 把 publishable run 5 月 12-25 日跑下来累计
> 暴露的项目问题、已 codify 的不变量、还没处理的痛点, 全部摊平到一个
> 索引里。 详细的不变量原文在 [CLAUDE.md](../CLAUDE.md), 详细 incident
> 在 [docs/sessions/](sessions/), 这里只做拓扑 + 未 close 项的 TODO list。

## TL;DR

publishable run 1000 agent × 14 day × 4 variant × N seed 这条管线累计
撞了 **3 类反复出现的工程故障模式 + 2 类内容/科学问题 + 1 类文化问题**:

| 类别 | 具体表现 | 发现频次 | 已 codified |
|---|---|---|---|
| **资源边界** | RSS 累积 / snapshot 反序列化峰值 / asyncio handler hang | 5+ 次 | 部分 |
| **并发自伤** | 错峰 spawn / LLM API burst self-DDoS / 守护脚本主动 kill | 4 次 | 是 |
| **wiring gap 静默漂移** | `getattr(obj, "name", default)` 把字段重命名吞掉 | 4 次同晚 | 是 |
| **测试覆盖盲区** | unit test 全绿 / integration 失败 / 真 worker 报废 | 7 个产线事故 | 部分 |
| **agent 故事内容真实性** ⭐ | phantom 女儿 / retail_worker drift / 双重计数 / 物理 impossibility | 6+ 处 | 部分 (有约定无 audit 工具) |
| **系统评测全缺** ⭐ | 4 个 finding · 0 个评测维度 · n=1 anecdotal evidence | **整个项目周期** | ❌ 完全空白 |
| **agent 系统架构 framework-borrow** ⭐ | 接成熟 framework 启动 MVP, 没 retrospect 顶层抽象是否服务 thesis — attention/4-archetype 等核心都 bolt-on | 6 处 架构层 | ❌ root cause 级 |

外加 **publishing 侧** (portfolio 网站 + 对外文档) 几个独立教训, 跟仿真
管线无关但属于同一项目交付的一部分, 也一起记下。

⭐ 标记的两类是这次复盘新增, 之前散落在 commit message 跟 task list 里
没有汇总; 第二个 (评测缺失) 是项目当前**最大的盲区**。

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
- ⏸ **disk space relief** (2026-05-27 挂起, 等买外置硬盘): `data/` 现在
  131 GB (149 个 snapshot.json = 126.9 GB / 96.9% 体积), 计划是把
  `data/experiments_archive_pre_2026_05_21/` (32 GB) + 完成 cell 的
  中间 snapshot 整个搬到外置硬盘, 本机只留 active run + final aggregate。
  可选: tar.zst 先压缩到 ~5 GB 再搬。 工具未写, 走到那一步再写
  `tools/cleanup_completed_cell_snapshots.py` 跟 archive 打包脚本

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

## 9 · Agent 故事生成 — 内容真实性 bug

**核心矛盾**: longform / VN 故事重建用 LLM 把 simulator events JSONL
转成可读 narrative。 LLM 会**自由发挥**, 产生**与真实数据不符的内容**,
读者一眼看不出, 但严格审计就破。 数据再多 narrative 一编就垮 — 这是
项目"信任度"的核心风险点。

**实测撞过的 6 类内容 bug** (5 月 22-25 累计, 散在 #152-178 task series):

### 9.1 Phantom 角色 / 信息 (凭空捏造)

- Mary longform v1 LLM 加了"一个女儿"角色 — 实际 personality profile
  里没有
- a0290 v1 写了"零售业过往" — 实际 agent 是 ICU 护士, 跟 retail_worker
  template 半残留
- → 修: 每个 fact 严格 grounded in `agent.{personality,life_history,
  relationships}`, prompt 显式列"可用 facts"
- Reference: #158 phantom 女儿修复, #177 a0290 v2 磨平 retail_worker bug

### 9.2 Identity drift across iterations

a0290 v1 是 ICU 护士 → v2 表面修了但底层 retail_worker template 残留
→ v3 才完全 ICU 化。 LLM 每次小修都可能引入新 inconsistency 不收敛。
- → 修: identity statement 写在 prompt 顶, 每次 iter 复用 v0 grounding,
  不让 LLM "重新理解" 角色
- Reference: a0290 v1 → v2 → v3 (#176-178)

### 9.3 物理 impossibility

agent 同一 tick 出现在两个地点 (Mowbray Road + ICU 同时), 因为 LLM 把
narrative-time 跟 simulation-tick 弄混。
- → 修: "6 顶帽子物理隐身" 系列规则 — 每段叙述显式 anchor 一个 tick +
  location, 同 tick 双 location 即报警
- Reference: #178 a0290 v3 "6 顶帽子物理隐身"

### 9.4 数字双重计数 / count 跟 distinct 混

- "擦肩 467" 实际是单 seed 同框 count, 写法暗示"她遇到 467 个**不同**
  的人" — count 跟 distinct 混了 → 后改"同框 / 看见 双层数字" 标注
- "3972 dialogue" 实际是 4 variant × seed 求和, 在 ch7 + appendix
  **双重计数** (一处 sum, 一处误以为是单 seed average)
- → 修: 任何数字标 source (seed N / variant V / 是 sum 还是 mean), 绝
  不写"她有 X" 暗示 distinct 的语言, 除非真是 distinct count
- Reference: #156 (467 修复), #161 (3972 双重计数), #162 (push density
  global dedupe)

### 9.5 LLM 痕迹 / dialogue 单调

5 段对话用同一句套话开头, LLM batch 生成时模板感未抹掉; 句尾 hedging
"或许 / 也许" 高频出现; 段落结构机械 (5 句 → 转折 → 升华)。
- → 修: **不掩盖, 标出来** — 加 highlight + 机制 note ("LLM 倾向于
  ...") 让读者看见; 下次生成强制 voice variation
- Reference: #152 抚平 LLM 痕迹, #158 NPC repetition 高亮, #164 system-log
  对话 / whisper-game 视觉

### 9.6 性别 / 身份冲突

simulator 给 agent 分配的 gender 跟 LLM 生成 narrative 用的代词不匹配
(personality JSON 里是 "她", LLM 写 "他")。
- → 修: `clean_text` pass 强制代词跟 source 一致, 加 method note 说明
- Reference: #152

**已落地的内容真实性约定** (CLAUDE.md 强制规则):
- LLM 痕迹**标出来不掩盖**: phantom 内容 / NPC repetition / 套话开头
  → 加 highlight + 机制 note
- 数据驱动语气 anchor: "她说" → "记录里她跟 agent_15 说...";
  "她每天都会" → "在 14 天 BL 模拟里, 她去 X 次"
- counting 双层: 当心 "擦肩" 这种隐含 distinct 含义的词, 用 "同框 /
  抬头看见 / noticed" 双值并列
- 角色 identity v0 固化 prompt header, 每次 iter 复用
- 数字必须 verified, 不准为叙述好看而编 ([对外报告 9 原则](https://github.com/york-zhouuu/-Synthetic-Socio-Wind-Tunnel-/blob/main/CLAUDE.md) 第 8 条)

**未做** (高优):
- [ ] `tools/audit_longform_grounding.py` 自动 audit: 把 narrative 里
      所有 fact-like claim 提出来, 跟 `agent.{personality,life_history,
      relationships,events}` JSON 字段做 fuzzy match, flag "无源" claim
- [ ] LLM 输出**结构化 grounding**: 每段附 ref `{tick: 1234, location:
      "Mowbray Road", source: events.jsonl L4567}`, audit 变机械
- [ ] **角色一致性 regression 套件**: 给 v3 加 test "提到 ICU 至少 N
      次 / 不出现 retail 关键词 / 性别代词全 '她'", 防 v4 再 drift

---

## 10 · 系统评测彻底缺失 (the no-eval problem)

**核心矛盾**: 项目跑了 14 天 × 1000 agent × 4 variant × N seed, 产出
4 类核心 finding (siphon / friction / routine-cliff / 3 hero longform),
但**从来没有任何 quantitative / qualitative evaluation** 告诉我们这些
finding **是否成立**。

**当前事实**:

```
✗ 没有 ground-truth          没人知道"真实 Lane Cove 居民 14 天会怎样"作为对照
✗ 没有 seed-cross robustness  4 个 finding 在 seed 43/44/45 上一致吗? 没系统跑过
✗ 没有 human plausibility     真人能区分 "simulator 生成" vs "真实 case study" 吗?
✗ 没有 simulator fidelity     agent 的 personality 跟 14 天行为自洽吗? 没量化
✗ 没有 counterfactual validity 4-universe 差异是干预贡献还是 LLM 噪声?
✗ 没有 cross-version regression  longform v3 比 v2 好还是坏? 没指标
✗ 没有 content grounding audit  narrative 每个 fact 都有 source 吗? 见 Section 9
```

**这是项目当前最大的盲区** — 所有 finding 都是 **n=1 anecdotal
observation**, 没经过任何科学口径 validation。 报告写得再漂亮, 对
学术读者 / paper reviewer 来说**等于零证据**。

### 缺失的 8 个评测维度

| 维度 | 问题 | 可行方法 |
|---|---|---|
| **Simulator fidelity** | agent 行为跟 personality+routine 自洽吗 | personality × action 互信息; perturbation test |
| **Cross-seed robustness** | 4 finding 在 seed 43/44/45 上一致吗 | 重跑 seed 44/45, effect size + 95% CI |
| **Cross-condition validity** | HP/PF/GD 跟 BL 差异显著吗 | bootstrap permutation test on noticed encounter |
| **Narrative plausibility** | 真人能区分 simulator vs real 吗 | Turing-style A/B test (8-10 readers × 12 paired snippets) |
| **LLM content grounding** | narrative 每个 fact 都有 source 吗 | `tools/audit_longform_grounding.py` (见 9.7) |
| **Reader comprehension** | 真人读懂报告核心 finding 吗 | 8-12 reader interview "what's the main finding" |
| **Counterfactual validity** | 4-universe 差异是干预 vs LLM 噪声 | hold seed fixed, 同 variant 重跑 5 次 LLM seed, 看 within-variant 方差 |
| **Cross-version regression** | longform v3 vs v2 哪个好 | rubric scoring (5 criteria × Likert), pre-registered |

### 10.3 关键 reframe — generative social science 的判定标准

上面 8 个维度都假设"评测 = 验证 finding 真的会在现实发生"。 这是
**错误的目标** — 项目本来就不是 prediction tool, 强行往这个 bar 上靠
永远 defend 不了。 generative social science 这个领域 30 年来 (Schelling
1971 偏见模型, Epstein-Axtell 1996 sugarscape, Axelrod 1997 文化扩散,
Reynolds 1986 boids) **没人用 ground-truth 验证 ABM**, paper 照样发,
学术价值站得住。

**领域共识**: 这类工作的 value 不是 "预测 X 数字", 是 "**让 X 这个
mechanism 进入可讨论 vocabulary**" — Epstein 称之为 "if you didn't grow
it, you didn't explain it"。 Schelling 71 年 paper 从来 never 校准 30%
同质偏好参数, never 拿模型跟真 census 比, 但它**第一次**让 "微弱
同质偏好 → 强 segregation" 这条 mechanism 进入了公共讨论 vocabulary。
20 年后这条 insight 重塑了住房政策 debate。

**对应到 SSWT**:

| 旧 framing (无法 defend) | 新 framing (可 defend) |
|---|---|
| "推送会让人走出附近性盲区" | "在 attention-gated 仿真里, hyperlocal push archetype 会产生 anchor concentration 而非 proximity dispersion — 是 attention 落点重分布而非物理 proximity 增加" |
| 要求: ground-truth real-world data | 要求: 仿真内部一致 + 跨 seed robust + 跟 literature 三角对 |
| 读者收获: "下次 deployment 会怎样" | 读者收获: "原来 attention 这块 design space 里有这种 dynamic, 之前没人指着它说过话" |

把 finding 从"现实预测"改成"仿真器内 emergent pattern + 机制依赖", **claim
变小, defend 边界一下子清晰** — 不是 lower the bar, 是这个领域的诚实
写法。 而且反直觉地, **scope 越窄的 finding 越值钱**, 因为读者知道
作者 know what they can and can't claim。

### 10.4 项目当前真做到了什么 (vocab / viz / affordance audit)

按 mechanism legibility 三层标准 audit SSWT 的实际贡献:

| 层 | 现状 | 评估 |
|---|---|---|
| **Vocabulary** | △ 部分 | "附近性盲区 / noticed vs 物理同框 / 4-archetype" 在项目内 well-defined, 但还没被外界 cite。 Schelling 用了 20 年才让"residential preference cascade" 进入主流 — 你有 vocabulary candidate, 是否真 pick up 看后面 1-3 年 |
| **Visualization** | ✓ **强** | 5 张 v7 figure + 2.5D anchor 地图 + 3 篇 longform 4-universe 对比 + 滚动 cinema — 项目最强部分。 "attention 落点重分布" 在 SSWT 之前没有可视化语言能指着说, 现在有了 |
| **Affordance** | △ 部分 | 4 archetype (BL/HP/PF/GD) 是真设计 dial, 但 currently tied to simulator — 真 designer 要套到 Apple Maps 具体决策, 缺一层"archetype → 真 product feature" 翻译 |

**Honest conclusion**: legibility 是个 N 年 process, **你做到了"建出可能
legible 化的 artifact"**, 还没到 "verified legible" — 但你能 verify 的
也就这一步, 剩下的看外界 uptake, 不可控。

### 10.5 能做的 3 种 reality-bridge + 1 个硬上限

**不需要 ground-truth 也能做的**:

| 方法 | 不需要 | 能 defend |
|---|---|---|
| **Baseline 跟真 Lane Cove 数据校准** | 不需要"真有人推过 hyperlocal" | "BL 仿真器无干预下的 POI visit 分布 / 通勤 / 走路 footprint 跟真 Lane Cove 对得上 (Wasserstein distance < X)" — Google Popular Times, ABS 2021 census, OSM, Strava 都能爬 |
| **Intervention effect 跟 literature 三角对** | 不需要 deploy | 你的 ×2.3 effect 跟 Nextdoor (Easton 2019) / hyperlocal app (Bertelli 2025) / attention spillover (Wood 2002) 的 +12-30% range 同向且量级相当 → 校准。 跑偏一个数量级 → 你有问题 |
| **真居民 baseline 描述 interview** | 不需要 deploy 干预 | 20-30 真郊区居民 30min 半结构化, validate 你**baseline 描述** 是否准确 — 真人是否真的有"附近性盲区"感觉? 描述方式像你 finding 1 吗? 不像说明 thesis 本身有问题 |

**永远做不到的硬上限**: 真去 Lane Cove deploy hyperlocal push 14 天后
测 noticed encounter 变化 — 这是唯一能 "100% 对应现实" 的方法, 也是 PhD
论文里都不会要求的 (cost/ethics/timeline 不可行)。 任何 reviewer 都不会
卡这个。

### 10.6 LLM bias — 项目最深的 open issue

LLM-driven agent 仿真有 **5 种 bias**, 全部跟 SSWT 相关:

**10.6.1 Demographic stereotype bias** — LLM 训练数据过表 WEIRD
(Western/Educated/Industrial/Rich/Democratic), "Lane Cove ICU 护士" 不
是真 Lane Cove ICU 护士, 是 LLM training data 里**"郊区 ICU 护士" 这个
stereotype 的 distillation**。

**10.6.2 Cultural narrative bias** — LLM 写 "Sydney 郊区生活" 时 filter
是英文主流叙事, 可能偷换成 generic-suburban-America 假设。 6 顶帽子 ICU
护士的情绪曲线 / 凌晨 2 点哭这种 narrative arc, 可能更多是 LLM "什么是
好故事" 的偏好, 不是真 ICU 护士经验。

**10.6.3 Behavioral pattern bias** — LLM 决定 "agent 在 HP variant tick
1234 会做什么" 时 pattern-match training data 里 **人们 respond hyperlocal
push 的 discourse** — 主要来自 tech-critical 媒体的 essay, 不是行为实测。

**10.6.4 ⭐ Reflexivity bias (最严重 / 最难解决)** — LLM 读过大量
"smartphone addiction / attention crisis / 附近性消失" 的 discourse。 你
让 LLM 模拟 "phone-distracted urban resident", 它返回的就是 training
data 里那些 essay 描述的样子。 finding "attention 被 phone 抢走" 是真在
simulator 里 emerge, 还是 LLM 把训练数据里的 attention-crisis discourse
**fed back to you** — **几乎无法区分**。 这是循环论证风险。

**10.6.5 Narrative resolution bias** — LLM 倾向 produce "起-承-转-合 +
insight" 结构, longform emotional climax 可能更多是 LLM 偏好, 不是数据
驱动 (#158 phantom 女儿 / a0290 v3 6 顶帽子的情感闭环都跟这条相关)。

### 10.7 LLM bias mitigation — 实际能做的 4 件事

| 方法 | 解决哪些 bias | 工作量 | 优先级 |
|---|---|---|---|
| **Multi-LLM 复现** — 同 setup 用 DeepSeek + Claude + GPT-4o 跑, finding 一致吗 | 10.6.1 / 10.6.2 / 部分 10.6.3 | 中, ~$300 × 3 model | 中 |
| **⭐ Rule-based agent ablation** — LLM 决策换成简单 rule (随机游走 / 固定 routine), finding 还在吗? 在 → LLM 不是 cause; 不在 → finding 可能是 LLM artifact | **关键**, 解决 10.6.4 reflexivity | 1-2 周 | **高** |
| **Census / ABS 校准 baseline 分布** — 1000 agent demographic 是否 match 真 Lane Cove (age × occupation × household) | 部分 10.6.1 | 1 周 | 高 |
| **真居民 interview 三角对** | 部分 10.6.1 / 10.6.2 / 10.6.5 | 1-2 月 | 中 |

**永远做不到** (诚实承认):
- Reflexivity bias **没法完全消除** — 只要用 LLM 模拟 "现代 urban 注意力",
  就有 LLM 把 attention-crisis discourse 喂回来的风险
- 能做的是: 把它**写进 limitation section**, 并用 rule-based ablation
  证明 finding 不只是 LLM artifact

### 10.8 Venue 适配性 — 项目去哪发

| 受众 | defensibility | 需要做什么 |
|---|---|---|
| **CHI / DIS / Critical Computing / Digital Humanities** | ⭐⭐⭐ 强 | 重 mechanism + provocation + viz, 不卡 ground truth — 当前工作量大概够投 CHI long paper / DIS critical design |
| **Generative agent papers** (Park 2023 同类) | ⭐⭐⭐ 强 | city-scale + attention + LLM narrative 是 unique 组合, 现在就能站 |
| **HCI urban computing / smart city** | ⭐⭐ 中 | 明确 reframe 为 "design space exploration" 而非 "real-world prediction" |
| **真 stakeholder (Apple/Google design)** | ⭐⭐ 中 | 把 archetype 从 simulator 解耦成独立 product 词汇 |
| **Quantitative social science / PNAS / AJS** | ⭐ 弱 | 当前不行, 补 cross-seed × literature 三角对 × ablation 1-2 周 + reframe 后可能勉强 |

**最 honest 评估**: 项目最独特的是**视觉表达 + LLM agent + 城市尺度 +
attention thesis** 的组合, 不是任一单维度。 强项 = 弱项的同一面: 量化
rigor 永远不会赢专做 quant 的人, 但在 design + visualization + LLM-mediated
urbanism 这个 niche 几乎没人 sit there。 **走 design venue 是 path of
least resistance + highest leverage**。

### 10.9 Why we haven't done this yet (诚实复盘)

- **Cost 心理门槛**: publishable run ~$300 / 4 variant × 14 day × β=4
  seed, 重跑做 cross-seed test 直觉上"贵"
- **评测需要人 + 时间**: A/B test / reader interview 不是单纯加代码,
  要找受访者
- **anecdotal signal 太强**: finding "好像 work" 的直觉太强烈, 心理上
  跳过 validation 直接进 narrative polish
- **没人写 eval harness**: 现在写也得 1-2 周, 不写又永远没有

### 风险 (诚实评估)

不做评测就投出去, **reviewer / 严格读者一翻就发现 "这是 demo 不是
evidence"**。 narrative quality 已经够高, 但**信任度上限完全卡在
evaluation 这步** — 没评测, 故事再好 = 装饰; 有评测, 即使部分 finding
不成立, **方法论本身仍然有价值**。

### 排期建议 (从 cheapest 到 expensive)

1. ⚡ **Cross-seed robustness** (1-2 天): 已有 seed 43/44 数据, 加跑
   seed 45, 4 finding 各算 effect size + CI; 这是最便宜也最可能动摇 /
   confirm finding 的一步
2. ⚡ **Content grounding audit** (1 天): `tools/audit_longform_grounding.py`
   规则式 string match, 把现有 3 篇 longform 过一遍, 看 phantom rate
3. **Counterfactual within-variant 方差** (3-5 天): 同 variant 重跑 5
   次同 sim seed 不同 LLM seed, 量化"4-universe 差异有多少来自干预 vs
   LLM 噪声"
4. **Turing A/B reader test** (1-2 周): 找 8-10 design researcher / 学
   术读者, 12 段 snippet 区分, target accuracy ≤60% 才算 narrative-plausible
5. **统一 eval harness** (`tools/eval_harness.py`, 2-3 周): 框架跑上述
   所有 quant 评测, 持续 regression
6. **学术 paper outline + reviewer-ready evidence** (1-2 月): 现有
   报告全是 design-researcher 风格, 缺一份 paper reviewer 能看的 evidence
   table + effect size + CI + ablation

### Open questions (需要决定)

- 评测优先级: **cross-seed robustness** vs **reader plausibility**
  谁先? (个人倾向前者, 因为后者依赖前者 — 在不知道 finding 是否 robust
  之前问 reader "可信吗" 是过早)
- ground-truth 怎么办: 真实 Lane Cove 居民 14 天 attention data 不存在
  → 是否接受"用 BL 仿真本身作为 ground-truth"的弱命题
- pre-registration: 是否在跑 seed 45 之前先 freeze "4 finding 的预期
  effect size 方向" — 避免事后挑数据

---

## 11 · Agent 系统架构 — 接 framework 而非按 thesis 设计

**核心矛盾**: 项目最初为快出 MVP 直接 fork / port 已有 generative agent
框架 (Park 2023 generative agents + Concordia / AgentSociety 等 inspiration),
拿来跑出 demo 之后**所有后续工作都在 patch 框架以服务 thesis**, 而不是
按 thesis 反推架构。 后果是 thesis-critical 的概念 (attention gate /
4-archetype intervention / noticed encounter) 都是 **bolt-on, 不是
first-class citizen**。 这是比 wiring-gap bug (Section 4) 更深一层的
root cause。

### 11.1 6 个具体表现

**(1) Attention gate 是 add-on, 不是核心**
- 现在: encounter event 先生成 (基于物理 proximity), 再做 attention filter
  决定 noticed / unnoticed
- 应是: agent 的 perception 本来就 attention-bottlenecked, encounter
  detection 走 attention 通道
- 后果: noticed vs unnoticed 永远存在歧义 ("看到但忽略" vs "根本没看到")
- 修起来需要重写 perception layer

**(2) Memory model 沿用 generative agents 套件**
- encounter / reflection / importance score 这套来自 Park 2023, 设计
  目标是 sandbox sim 通用性
- SSWT thesis 关心的是 attention budget 怎么花 — generic memory 没这层
- 后果: 没有 "她今天的注意力预算被 X 件事吃掉 Y%" 这种 thesis-aligned 量纲

**(3) Personality 5-trait big-five 直接套**
- extraversion / openness 等是 big-five 标配 (McCrae 1992)
- 跟 thesis "attention-induced nearby blindness" 没正面挂钩, 哪些 trait
  影响 nearby noticing 是**ad-hoc 后挂**, 数据反推不是机制预测
- 后果: responder profile 分析全是后验, 没有先验机制

**(4) Tick / day / phase 时间粒度跟 thesis 不匹配**
- 288 ticks/day = 5 min/tick — 从 generative agents 模板继承
- thesis 关心的 attention switch 秒级 / dwell 分钟级 / narrative arc 小时级
  — 全在不同 scale
- 后果: 看不到秒级 attention dynamics, dwell 统计粒度粗到几乎没法测

**(5) Push system 接进 do_something operation**
- generative agents 的 do_something 是 "agent 决定下一个 action"
- push 作为 input feed 给 do_something, 但**跟 routine adherence /
  personality 怎么交互全在 LLM 黑盒里**
- 应是: push → attention salience 调整 → behavior change 三步分离可测
- 后果: 4-archetype 差异在 LLM 黑盒里, 没 inspectable mechanism layer
  (这条直接 enable 了 [10.6.4 reflexivity bias](#1064-⭐-reflexivity-bias-最严重--最难解决))

**(6) DialogueService / operation pool 等 framework 残留**
- 从框架借来用着, 但 thesis 不关心 dialogue 内容 quality, 只关心
  dialogue 是否发生
- 后果: DialogueService 持久化 / dialogue counter wiring gap 等问题都
  因为它**跟 thesis 不直接相关 → 没人 own → 容易忽视**

### 11.2 Root cause

MVP 启动时**借框架是合理选择** (快出 demo, 不重新发明轮子)。 错的不
是借, 是**没在迭代过程中 retrospect 架构是否还服务 thesis**。 thesis
是 attention-induced nearby blindness, 但 codebase 顶层抽象到现在仍然
是 "generative agents 通用 sim", 中间没有 thesis-derived layer。

### 11.3 已经付出的代价 (跟其他 Section 联系起来看)

| 表层问题 | 真因 (本节) |
|---|---|
| Section 4 · 4 个同模式 wiring gap bug | thesis-critical 字段是后挂的, 没 owner |
| Section 8 · 数据分析口径混乱 (noticed vs distinct_pairs) | noticed 是后挂概念, 不是 first-class |
| Section 10.6.4 · reflexivity bias | attention 行为完全依赖 LLM 决策, 没 attention-budget 层独立 |
| Section 5 · test 8 类问题 | 大部分 thesis-critical invariant 没在 framework 抽象里, test 抓不到 |

### 11.4 未做 — 3 种取舍

| 路径 | 工作量 | 何时选 |
|---|---|---|
| **A. 重写 attention layer** 让它独立于 LLM 决策 — attention 有自己的 budget / decay / refresh, LLM 只 sample from attention state | 大, 3-4 个月重构 | 如果继续 push 这个 thesis 当主项目 |
| **B. 诚实承认 + enumerate** — paper Architecture section 明确"这是 framework-borrow that we adapt", 列哪些 borrowed vs custom | 小, 1 周写作 | 如果走 design venue (CHI/DIS) — reviewer 看到诚实承认反而加分 |
| **C. 下一个 thesis 时复用教训** — 先写 thesis 1-pager, 再决定借哪个 framework, 哪些必须自己写 | 0 工作量, 元规则 | 项目 wrap up 之后 |

### 11.5 元规则 — 给下一个项目

借成熟 framework 启动 MVP 是合理选择, 但**必须每隔几周 retrospect "框架
的顶层抽象还服务 thesis 吗"**。 不 retrospect 就会渐进式偏离, 等到发现
已经付了很多技术债 + thesis-critical 概念全是后挂。

具体的工程约定:
- 新 OpenSpec change 的 design.md SHALL 显式问 "这次改动让 framework
  顶层抽象更 thesis-aligned 还是更通用 sandbox sim?"
- thesis-critical 概念 SHALL 有 dedicated module / first-class type, 不
  能只是 string tag (现在 "noticed" 是 `tags: list[str]` 里的一个 string)
- bolt-on 接进 framework 的新概念 SHALL 列 owner — 谁负责跨整个 codebase
  保证它的语义一致

---

## 12 · 对外写作 / 文档约定

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

## 13 · Publishing 侧 (portfolio 网站) 教训

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

## 14 · 横切观察 · 模式与下一步

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

**高优** — 信任度卡死, 这几条不做项目对外没法 defend:
- [ ] ⭐ **Cross-seed robustness** (1-2 天): 跑 seed 45, 4 finding
      effect size + 95% CI, 看是否 across seeds 一致 — 这是 cheapest
      validation, 最值得先做
- [ ] ⭐ **`tools/audit_longform_grounding.py`** (1 天): 把 3 篇
      longform 过一遍, 量化 phantom rate
- [ ] retry-network-blip-tolerance change tasks 落地 (proposal 已写好)
- [ ] backlog 1.9 hot-path 之外的 LLM call 也加 `asyncio.wait_for`
- [ ] 全 codebase audit `getattr(x, "...", default)` → 直接属性
- [ ] CLAUDE.md 列的 4 个 high-priority test 补上

**中优**:
- [ ] **Counterfactual within-variant 方差** (3-5 天): 同 variant 同
      sim seed × 5 个不同 LLM seed, 量化"4-universe 差异有多少来自
      干预 vs LLM 噪声"
- [ ] **Turing A/B reader test** (1-2 周): 8-10 reader × 12 paired
      snippet, target ≤60% distinguish accuracy
- [ ] **角色一致性 regression 套件**: prevent v4 longform iter 再
      drift identity
- [ ] backlog 1.7 A 进程间共享只读数据 / 1.7 D fork-based spawn
- [ ] `tools/check_git_hygiene.py` pre-commit hook
- [ ] backfill 早期报告数据口径 (noticed vs 同框)

**低优**:
- [ ] **统一 `tools/eval_harness.py`** (2-3 周): 持续 regression 跑上
      述所有 quant 评测
- [ ] **学术 paper outline** (1-2 月): reviewer-ready evidence table +
      effect size + ablation, 跟现有 design-researcher 报告并行
- [ ] backlog 1.14 单 worker 多核并行化
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
