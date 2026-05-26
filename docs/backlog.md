# Backlog — 已识别但暂不开发的需求

记录用户确认过"需要做、但暂时不进开发流程"的事项。每条带上下文 + 优先级
+ 触发条件（什么时候应该把它从 backlog 移出来变成 OpenSpec proposal）。

---

## 1. Push 内容个体化（GD / PF）

**记录时间**：2026-05-17

**背景**：HP (HyperlocalPush) 已经过 `push-content-individualization` capability
精细化——5 个 PushTemplate × 5 audience variant + PushPersonalizer 路径。但
另外两个干预 variant 没走个体化：

- **GD (GlobalDistraction)**：10 条 generic global news headlines，所有 target
  收到同一条 broadcast。14 天 × 5 推送/天 会有大量重复。
- **PF (PhoneFriction)**：现已扩到 19 条 nudge templates（带 Lane Cove 地标 +
  时段 + 风格变化），但仍是 broadcast——所有 agent 同一时刻收到同一条。

**理想方向**：让 GD / PF 也走 PushPersonalizer，用 setup_content_cache 里的
`identity_text` + `life_history` 个体化 push：
- 对 35 岁有娃的设计师，PF nudge 提"孩子在 Canopy Park 等你"
- 对 65 岁退休志愿者，PF nudge 提"Plaza 长椅有人在等下棋"
- GD 也可按职业 / 兴趣个体化（财经 vs 娱乐 vs 体育 ……）

**优先级**：低。当前 D2 (β=10 publishable) 用 broadcast 路径已能给出 H_info /
H_pull 方向证据；个体化是"如果方向对，下一步加深效果"的扩展。

**触发条件**：D2 跑完，contest.json 显示 H_pull / H_info 方向有效但 effect
size 偏弱时考虑——届时 push 内容个体化是首要 amplification lever。

**估工**：1.5-2 hr 代码 + 0.5 hr 测试。

**Owner**：未指定。

---

## 1.5. 用 Doubao Seed Lite 替换 Gemini 3.1 Flash Lite（generate_message 路由）

**状态**：✅ 已实施（2026-05-17，比 backlog 描述更彻底）——
Doubao 不只是"backup"，已经是 `generate_message` 的**主路径**。当前
2-provider 切分架构（按"模型选型决策"而不是 tier 标签描述）：

| LLM 调用 | 流量占比 | Provider | 模型 | 选型理由 |
|---|---|---|---|---|
| `do_something`（决策） | ~31% | **DeepSeek** | v4-pro | 多步推理 + 工具选择 + 计划生成，质量门槛最高 |
| `generate_message`（对话生成） | ~69% | **Volces Doubao** | doubao-seed-2-0-lite-260428 | 1-2 句中文短文本，主求快 + 便宜 + 原生中文 |
| `remember_conversation` | 小 | DeepSeek | v4-flash | 200-500 字摘要，中等质量够用 |
| `reflect` | 小 | DeepSeek | v4-flash | 同上 |
| `score_importance` | 小 | DeepSeek | v4-flash | 单 int 输出（0-9），质量门槛低 |

**Fallback chain for generate_message**：
- 1st: Volces Doubao（首选，2026-05-17 user-added）
- 2nd: Gemini 3.1 Flash Lite（Volces auth/网络失败时）
- 3rd: DeepSeek v4-flash（两上家全挂时）

**实现细节**：
- `tools/tier_llm_factory.py` 新增 `provider="volces"` 分支，复用
  `_DeepSeekTierClient` 适配器（Volces Ark `/api/v3/chat/completions`
  是 OpenAI-compatible），指向 `VOLCES_BASE_URL`，注入 `extra_body={}`
  （Volces 不接受 DeepSeek 的 `thinking` extra）
- `.env` 配 `VOLCES_ARK_API_KEY`（机器本地，不进 git）
- `tools/run_variant_suite.py:638-670` 起 Volces tier client →
  注入 `tier_clients["doubao_flash"]` → 路由 `generate_message` 到此 key；
  try/except 链 fallback 到 Gemini → DeepSeek v4-flash
- 实测：`generate_message` 路由生效后，DeepSeek 单边压力降 69%，整体
  吞吐 1.5-2× 提升

**为什么这样切分而不是全 Doubao**：
- `do_something` 是 1000-agent run 的"决策大脑"——要规划 + 工具选择
  + 多步推理。Doubao Lite 当前推理深度不够支撑 1000-agent decision
  consistency，必须用 DeepSeek v4-pro 这类顶档模型才稳得住实验内涵
- `generate_message` 是对话生成——1-2 句中文短文本，Doubao Lite 又快又
  便宜还 native 中文，质量够，单价 ~1/8 DeepSeek v4-pro
- 这样既保住决策质量，又把 quota 压力分到两家 provider，单边出问题不
  整夜停摆——本来 1.5 想要的"备用发电机"价值，已经在这个切分里实现了

**触发条件 / 后续工作**：
- 当 Doubao Lite 长 context（>8K）质量明显下降 → 看用 Doubao Pro 或
  其它模型
- 当 `generate_message` 还想 100% 个体化（backlog 1）→ Doubao 单价低反而
  让个体化变可行

**关联**：[[wire-emit-llm-call]] 已 emit per-call provider 字段，下游
audit 可以分 provider 看 latency / success / fallback rate。

**记录时间**：2026-05-17

**新加 provider**：Volces / 火山引擎 Doubao
- Endpoint：`https://ark.cn-beijing.volces.com/api/v3/responses`
- 默认模型：`doubao-seed-2-0-lite-260428`（字节跳动 fast 模型）
- API key：`.env` 里的 `VOLCES_ARK_API_KEY`（2026-05-17 设置）
- API 风格：Volces Ark "responses" 接口，input 数组 `{role, content=[{type, text|image_url}]}`
  支持多模态——**与 OpenAI chat-completions 不同**，需要新的 tier-client adapter

**何时考虑**：
- Gemini 不稳定 / 撞 quota → 切到 Doubao
- 跑超大 run（β=30+）想分散到 3 个 provider 提高总并发
- 想试 multimodal feature（agent "看见"图片 push）

**实施工作量**：~半天
- 在 `tools/tier_llm_factory.py` 加 `_VolcesTierClient` 类（mirror
  `_GeminiTierClient` / `_DeepSeekTierClient` 结构）
- 处理 Ark 的 `input` 数组格式 vs OpenAI `messages` 格式
- 加 `VOLCES_MODELS` dict + provider="volces" 入 `build_tier_clients`
- 在 run_variant_suite 切 generate_message tier 到 "volces" key 测一遍

**优先级**：低。当前 Gemini Flash Lite 工作正常；只在出问题时启用。

**Owner**：未指定。

---

## 1.7 多 worker 内存优化 + 去除运行时重复计算

**状态**：⚠️ B + F 已实施（2026-05-19），其它（A/C/D/E/H）仍 pending。
见 CLAUDE.md `memory-auto-restart` 不变量。

**已完成**：
- ✅ **B** Auto-restart on memory threshold：env `RSS_RESTART_MB` 控制阈值，
  `synthetic_socio_wind_tunnel/orchestrator/multi_day.py::_init_memory_management_hooks`
- ✅ **F** 周期性 `gc.collect()`：env `GC_EVERY_N_TICKS` (默认 200)
- ✅ **前置**：修了 `tools/run_variant_suite.py` 的 SIGUSR1 graceful_stop
  污染 bug（不再写假 `seed_N.json` + 不再 cleanup partials），否则 B 每次
  自杀都会损坏数据

**未完成**（按 ROI 排序，等下次需要时做）：A mmap atlas / C cold prune /
D fork-based / E dataclass slots / G K=1 / H 缓存 sample_population

**记录时间**：2026-05-18

**背景**：D2 attempt 4 (2026-05-18) 跑 4 seed × 4 variant = 16 worker
publishable 时，48 GB 单机内存被 D2 完全吃满 → 41 GB swap + 26 GB
compressor，Activity Monitor 显示 "Memory Used 138 GB"，workers 因 swap
thrash 速度比预期慢 50%（22 hr → 30+ hr）。最终凌晨 03:00 kill 掉
seed44 + seed45 两 suite 释放内存，β=2 跑完。

**问题诊断**：
- 每 worker 进程独立加载所有数据，**完全没共享**：
  - Atlas (~100 MB) × 16 = 1.6 GB（同一份地图）
  - shared_memories (~30 MB) × 16 = 480 MB
  - archetype / conversation_topic / social_prior_rule (~10 MB) × 16 = 160 MB
  - setup_content_cache 加载（per-seed 不同，但每 worker 读盘 + 解析独立）
  - Python interpreter + libraries (~700 MB) × 16 = 11 GB
- 每 worker 独立累积 MemoryStore (~1.5 GB peak after 14 day) × 16 = 24 GB
  → MemoryEvent 全在 RAM，没有 paging-to-disk 机制
- 每 worker 重复跑 `sample_population` / `build_location_pools` /
  `compute_social_priors_for_population`（同 seed 同结果）

**优化方向**（按 ROI 排序）：

### A. 进程间共享只读数据（高 ROI, 中等工作量）
**状态**：⚠️ 2026-05-20 实测后 **defer** — 原 "1 天" 估计低估了 Python
对象模型的本质约束，真做需 4-6 小时风险较高的 refactor，而 β=4
publishable 现状下 ROI 已不显著。

#### 为什么 "mmap atlas" 在 Python 里不像 C/Go 那么简单

普通理解里 "用 mmap 共享地图" 是：把地图 dump 成一个 binary 文件，
4 个 worker 各自 mmap 这个文件，操作系统的 page cache 自然让 4 个进程
看到的是同一段物理内存——节省 RAM。**这在 C / Go / Rust 里成立，因为
那些语言可以直接操作 raw bytes。**

但 Python 不一样。Python 里的"对象"是带 refcount 的 PyObject 结构体，
住在堆上、每访问一次都要改 refcount。哪怕底下的 raw bytes 来自 mmap'd
文件，**每个 worker 进程做 `pickle.load(mmap_file)` 时仍然会在自己的
heap 上 allocate 一整个对象图**——`Region` / `Building` / `OutdoorArea`
那 16 万个对象在每个 worker 里都是独立分配的。Mmap 文件只是被读了 4 次，
没有任何"共享"。这就是为什么实测下来 atlas 还是 164MB × 4 = 656MB。

#### 真正能让 4 个 worker 共享 atlas RAM 的 3 条路径，**每条都要重写 Atlas accessor**

| 路径 | 怎么共享 | 工作量 | 风险 |
|---|---|---|---|
| **(a) `multiprocessing.shared_memory`** | Atlas 序列化成一段 raw bytes 放在共享内存段，所有 Atlas accessor（`get_building` / `list_workplaces` / `connection_graph`）改成从 bytes lazy-parse | ~4-6h | 中（要重写 ~30 个方法，加 facade） |
| **(b) numpy.memmap arrays** | Atlas 几何字段（Coord / Polygon / 邻接表）转成 numpy 数组存到磁盘，每 worker `np.memmap` 同一文件——numpy 支持 OS page-cache 共享。其它字段（building_type / name 等 str）还得另想办法 | ~4-6h | 中-高（Atlas 几何与字符串混杂，numpy 不天然支持 dtype=object） |
| **(c) fork-based worker（即 backlog 1.7 D）** | Parent 进程 load Atlas 一次，然后 `os.fork()` 出 children → COW（copy-on-write）让 children 共享 parent 的 RAM 页面。**但当前 worker 是 `nohup ... &` 独立 shell 进程，不是 parent fork** | ~2 day（重写 launcher 协调模型 + macOS Apple Silicon 的 fork/objc 限制） | 高 |

**为什么 pickle / msgpack 这种"换个序列化格式"路径不算解**：换格式只
解决 cold-start 时间问题，**对 RAM 共享毫无帮助**——每 worker 反序列
化时还是分配自己的对象图。实测 JSON 0.27s vs pickle 0.47s，pickle 反而更慢；
也就是说 cold-start 不是瓶颈，根本不值得换格式。

#### 当前 D2 (β=4) 实际帐目

- 单 worker Atlas 实测 RSS：164MB（buildings=5722, outdoor=4257）
- 4 worker 重复占用：~656MB
- 项目已有的 worker RSS cap：2500MB / worker（`RSS_RESTART_MB=10000` 时
  10000，但通常按 backlog 1.7 B 设 2500）
- Atlas 占单 worker 的 6.5% RSS——**远低于 MemoryStore（55-70%）和
  agent_runtime / setup_content（15-20%）这两个大头**
- 已落地的内存优化（1.7 B auto-restart + F gc.collect + cold-prune
  encounter + slots-MemoryEvent + snapshot-prune-before-write）合计
  能压住 RSS 不爆——atlas 不在关键路径上

#### 何时触发回来做

- **β scale 翻倍**：跑 8+ worker 同时（β≥15），656MB → 1.3GB+，atlas 开始
  挤其它优化预算
- **跨机分布式**：搬到多机部署后，每机 RAM 单独算 budget，atlas 复制成本
  在 budget 紧的机器上变明显
- **新增 atlas 大头**：如果后面 atlas 嵌入 high-res 几何 / 大量额外
  building metadata 涨到 500MB+，6.5% 变 20%+，那就值得做
- **fork-based worker（1.7 D）做了之后**：fork + COW 是免费午餐，做了 1.7 D
  自动就把 atlas 共享了，不需要单独做 (a)/(b)

#### 当前一定不做的原因 summary

不是不能做，是 ROI 倒挂：4-6h 风险性重写换 ~600MB（占总 budget 1.2%），
而同样的 4-6h 投到 backlog 1（push 个体化）或 1.8（baseline-prefix-share）
直接给论文带 25% wall 减少 / 实验有效性扎实化——价值高一个数量级。

- Atlas 用 `mmap` 持久化 → 16 worker 共享同一份 100 MB 而不是 1.6 GB
- 同样适用于 shared_memories / archetype / setup_content_cache
- 估省：~2-3 GB
- 工作量：~1 day（atlas 重做成 mmap-backed format）

### B. **Auto-restart on memory threshold**（**首选**，低风险）⭐
- D2 attempt 4 验证：长跑 worker 内存里 ~70% 是"历史废纸"，restart 后从
  snapshot 重新加载，紧凑度提升 5-10x（参考 16:56 那次 restart，全机
  内存压力 138 GB → 23 GB 的现象）
- 实施：worker 启动时启 watchdog 线程，监 self RSS。> 阈值（如 2.5 GB）
  时触发 SIGUSR1 → HotfixSignalHandler → 写 snapshot → 优雅退出 →
  coordinator / 外部 launcher 自动 `--resume`
- 等价"运行时手动 GC"——把今天我们手动 kill + resume 的痛苦操作自动化
- 估省：每 worker 永远不涨过 2.5 GB（实际峰值可能去到 3 GB）→ 全 worker
  总 RAM 占用 ~50% off
- 工作量：~2-3 hr
- 风险：极低。HotfixSignalHandler / snapshot / resume 链路都已经在
  run-resilience + tick-level-resume capability 里验证过

### C. **Cold MemoryEvent prune**（中 ROI，中风险）
- 每 sim 日结束时，遍历 MemoryStore，丢掉满足条件的 events：
  - day_index < current_day - 3（4 天前的）
  - kind != "life_history"（保留 pre-sim 重要回忆）
  - kind != "reflection"（保留 daily summary）
  - importance < 0.5（低重要性）
- 保留：近 3 天 events、life_history、reflection、高 importance 关键时刻
- 估省：每 worker 800 MB - 1.5 GB（大部分 routine event 被清）
- 工作量：~1 day（实现 + 单测 + 验证不影响检索质量）
- 风险：可能损失 long-range 历史检索；需要看 thesis 实验是否依赖

### D. fork-based worker spawning（中 ROI，需要重构 launcher）
- 当前用 subprocess 起 worker，无 page sharing
- 改 `multiprocessing.fork` → child workers 自动 share parent 的 atlas
  / library page (COW)
- 估省：~5-8 GB（library 共享）
- 工作量：~2 day（run_variant_suite 重构）
- 注意：macOS fork() 在 Apple Silicon 上有 Objective-C / GIL 限制

### E. 紧凑 MemoryEvent 表示（小工作量，可叠加）
**状态**：✅ 已实施（2026-05-20）。MemoryEvent 之前其实已经是 @dataclass(frozen=True)，
本次只加 `slots=True`。同步加给 `MemoryQuery` + `DailySummary`。
副作用修复：`memory/service.py::_event_to_json_fast` 之前用 `ev.__dict__`，
slot 类没有 `__dict__`——改为直接 attribute access（在 CPython 实际更快）。
Regression guard 在 `tests/test_memory_event_slots.py`。
- Pydantic BaseModel → `@dataclass(slots=True)` 替换
- 每 event 省 ~50% 内存
- 估省：500 MB - 1 GB / worker
- 工作量：~半天（搜替换 + 接口测试）
- 风险：丢 Pydantic validation，但 MemoryEvent 是内部数据结构，可接受

### F. 周期性 `gc.collect()` + `malloc_trim`（quick win）
- Python heap 长跑后有 garbage cycles 不被自动回收
- 每 N tick (e.g., 200) 显式 `gc.collect()`
- macOS 还可以调 `malloc_zone_pressure_relief` 让 OS 收回
- 估省：100-300 MB / worker（清 garbage）
- 工作量：~1 hr
- 风险：零

### G. snapshot 保留策略：K=2 → K=1（小 ROI，极简单）
**状态**：✅ 已实施（commit `4c6d99b`，establish-observability-baselines 一起带的）。
`SnapshotPolicy.keep_last_k` default 已是 1；env `RESILIENCE_SNAPSHOT_KEEP_LAST=2`
可恢复旧行为。
- 改 `_SNAPSHOT_KEEP_K` 常量
- 实际是磁盘优化非内存优化，估省 ~200 MB 磁盘 / worker
- 工作量：30 min

### H. 去除运行时重复计算（小 ROI，简单）
**状态**：✅ 已实施（2026-05-20 narrow scope）。
`synthetic_socio_wind_tunnel/data_loader/population_cache.py::cached_sample_population`
缓存 sample_population 输出（~10-20s/spawn）到
`data/population_cache/v1/<sha16>.json`，run_variant_suite 已切换。
**未缓存 `build_location_pools`**：那函数消费 caller 的 rng，HIT 时跳过会
让下游 `build_scripted_plan` 看到没 advance 的 rng → 决定性破坏。
env `POPULATION_CACHE_DISABLE=1` 可关闭。8 个 regression test in
`tests/test_population_cache.py`，含 caching-doesn't-change-output 不变量。
- `sample_population` / `build_location_pools` 同 seed 同结果，可缓存
- 估省：~30 sec setup time / worker（时间，非内存）
- 工作量：~1 day

---

### ~~原 SQLite-backed MemoryStore 方案~~（已替换）

最初方案是把 MemoryStore 换成 SQLite/DuckDB-backed。**已经被 B (auto-restart)
+ C (cold prune) 组合替代**，理由：

- SQLite 方案工作量 3-5 day，需要重新设计 retrieve 接口，单测大量重写
- B + C 组合只要 1-2 day，达成相似的"持续低内存占用"效果
- B 风险极低（复用已有 HotfixSignalHandler）；SQLite 方案有 storage 后端
  兼容性 / retrieve 性能等多个未知数
- 长跑场景下 SQLite 写 IO 反而可能比 B 的"周期性 restart from snapshot"
  更慢

如果未来跑 β ≥ 30 publishable（半年级长跑）或想做永久持久化，再考虑
SQLite。当前 β=4-10 不需要。

---

**实施触发**：下次想跑 β ≥ 6 publishable 时做 B + F + G（半天工作）。
β ≥ 10 加 A + C（额外 2 day）。

**推荐组合**（按 ROI 排序）：

| 组合 | 工作量 | 内存收益 | 风险 |
|---|---|---|---|
| B (auto-restart) only | 2-3 hr | 每 worker 永封顶 2.5 GB | 极低 ⭐⭐⭐⭐⭐ |
| B + F (auto-restart + gc) | 半天 | 同上 + GC 清 100-300 MB | 极低 ⭐⭐⭐⭐⭐ |
| B + F + C (+ cold prune) | 1.5 day | 进一步降至 ~1 GB / worker | 中 ⭐⭐⭐⭐ |
| B + F + C + A (+ mmap atlas) | 2.5 day | β=10 publishable 单机舒服 | 中 ⭐⭐⭐⭐ |
| 全套 (含 D fork) | 5 day | β=15+ 可行 | 中-高 |

**Owner**：未指定。

---

## 1.8 baseline-prefix-share：避免重复跑 baseline phase

**记录时间**：2026-05-18

**背景**：D2 attempt 4 跑下来发现，同 seed 下 4 个 variant 的 **Day 0-3
（baseline phase）完全一样**——没 push，agent 行为只受 seed 决定，跟
variant identity 无关。当前架构让 4 个 worker 独立跑了 4 遍同样的 Day 0-3。

**浪费量化**：
- 每 seed：3 个 intervention variant × 4 baseline day = 12 worker-day 重复
- D2 attempt 4 (4 seed) = 48 worker-day 重复
- 按 ~1 hr/worker-day 折算 = **~48 hr 冗余 wall**
- 即总 wall ~22-30 hr 中有 25-30% 是重复

**优化方案**：tick-level-resume 已经有 snapshot 基础，加 baseline-prefix-share：

```
新执行流程（per seed）：
1. seed42 baseline 单独跑 day 0-3 → 写 day3_checkpoint.snapshot
2. seed42 baseline 继续 day 4-13（作为 control）
3. seed42 hp / gd / pf 各自从 day3_checkpoint 续，跑 day 4-13
```

收益估算：
- 总 worker-day: 4 × 14 = 56 → 14 + 3 × 10 = 44 = 省 21%
- D2 attempt 4 (4 seed × 4 variant) 总 wall: ~22-30 hr → ~17-23 hr
- 节省 ~5-7 hr

**实施关键点**：
- snapshot 必须包含全部 mutable state（已有，tick-level-resume capability）
- launcher 协调：baseline worker 先跑 day 0-3，写 checkpoint，其它 3 个
  variant worker 等 checkpoint 就绪后并行启动（fork-style）
- baseline 继续跑 day 4-13 的同时其它 3 个并行跑
- 写 checkpoint 的 worker 需要 SIGUSR2 类似机制告知 launcher 就绪

**实施成本**：~1-2 day
- launcher 协调逻辑改：~50 行
- baseline_snapshot_at_day=3 机制：~30 行
- 单测：~100 行（验证 snapshot 内容、checkpoint 等价性、resume 后行为等于
  原跑）
- 风险：snapshot round-trip 已被 tick-level-resume 测过，但 4 个 variant
  从同一 snapshot 同时启动是新场景

**触发条件**：下次跑 β ≥ 4 publishable 之前先做。比纯内存优化（1.7）
ROI 更高——直接 25% wall 减少，工作量更小。

**对实验有效性影响**：理论上零影响——baseline phase 4 个 variant 本来就
应该等价（只是同一段计算重复跑了 4 次）。snapshot round-trip 已验证
state 等价性。

**Owner**：未指定。

---

## 1.9 所有直接 LLM call 加 asyncio.wait_for 硬超时兜底

**状态**：✅ 已实施（截至 2026-05-19，5 个调用点全部 wrapped）。
regression guard 在 `tests/test_direct_llm_timeout_guard.py`（源码扫描
保护防回退）。openspec `harden-worker-resilience` 形式化进 spec。

调用点 timeouts（per-site，不统一）：
- `memory/reflection.py::reflect` — 60s
- `memory/importance.py::score_importance` — 30s
- `agent/planner.py::Planner.replan` — 30s
- `data_loader/lanecove.py::_generate_life_history_for_one` — 300s
- `data_loader/lanecove.py::_generate_identity_text_for_one` — 120s

**2026-05-20 复盘补充**（hang 又出现 + scout 验证 + Plan B 实施）：

scout 跑 1 seed × 4 variant publishable，5 个工作小时后**4 worker 同时
hang ~25 min**。SIGUSR1 不响应（asyncio loop 锁死）。手动 SIGKILL 后从
snapshot resume 1 个 baseline 验证 30 min 又 hang 一次同样模式。

**Solid 证据**（不是嫌疑）：
- 4 worker 都 stuck 在 `_pthread_cond_wait`（kernel mutex），主线程
  `_queue_SimpleQueue_get`
- 同时性：3 个 worker 在 10:45:04 UTC 同时静默
- SIGUSR1 send 后 60 秒 worker 仍 alive (asyncio loop blocked)
- Thread 数 10min→20min 从 4 → 22 增长（ThreadPoolExecutor 扩容）
- 健康栈 baseline：主线程在 `selectors.select()` （正常 event loop wait）
- 卡的时候栈一样 — **意味着不是 Python 代码层 deadlock，是 OS/network 层卡死**

**最一致的 root cause（无法 100% solid 证明，需要 sudo + py-spy）**：
asyncio + httpx + macOS 网络栈交互。`httpx.AsyncClient` 在 sync startup
建一份，4032 个 fresh `asyncio.run()` loop 复用——httpx 内部 asyncio
primitives 跨 loop 状态损坏。多 worker 并发 APIConnectionError 时踩到。

**Plan B 落地（2026-05-20 晚上）—— 接受 bug 存在 + 自动救援**：

1. **OperationPool 引入 env 控制 handler timeout**:
   `OPERATION_POOL_HANDLER_TIMEOUT_SEC=90` (默认 120s → 90s)
   - hang 不再 25min 锁住 → 最长 90s 强制 fallback
   - regression test in `tests/test_operation_pool_env_timeout.py`
2. **httpx pool read_timeout 推荐 60s** (默认 300s):
   `RESILIENCE_POOL_READ_TIMEOUT=60`
   - publishable 平均 LLM 响应 < 30s，60s 远超容差
   - hang 时 httpx 自身 60s 后报错，不再持续 30 min
3. **retry attempts 推荐 2 次** (默认 3 次):
   `RESILIENCE_RETRY_MAX_ATTEMPTS=2`
   - 单次 op 总等待上限从 24s 降到 16s，更快进 fallback
4. **RSS_RESTART_MB 推荐 6000** (从 10000):
   - 主动每 2-3 hr restart 一次，**阻止坏 asyncio 状态长期累积**
   - 每次 restart 损失 ~1 min wall（resume from snapshot）
5. **watchdog 作为第 5 观察通道默认启用**:
   `tools/watchdog_wal_deadlock.py` 用 bash while-true loop 包，每 60s
   检测一次 WAL stale > 300s
   - 真 hang → SIGUSR1 → SIGTERM → SIGKILL → 自动 resume
   - 总损失：~7 min wall per hang
6. **preflight 加 watchdog availability check + 11 个 env vars 推荐值
   全部更新**

**预期 publishable 14 天 × β=4 effective behavior**:
- 预计 16-48 次 hang occurrence
- 每次 hang 损失 ~7 min wall + 1 worker restart
- 总损失 ~2-5 hr 在 22-30 hr 总 wall 上（10-20%）
- 数据完整性 100%（snapshot resume + per-day summary persistence）
- 人工干预 0 次（全自动）

**留作未来工作**:
- 真 root cause 需要 sudo + py-spy 在 hang 现场 attach 取 Python 栈
- 或者大架构改：换持久 asyncio loop / 换 sync HTTP + ThreadPool
- 当前 Plan B 是 mask + auto-recover，不是 root fix

**记录时间**：2026-05-18

**背景**：D2 attempt 4 (2026-05-18) hit day-end deadlock 6 次——多个
worker 在同样的 day-end reflection 调用点 hang 死 40-80 min 没醒。已对
`_process_ops_hook` 里 `maybe_reflect` 加了 60s `asyncio.wait_for` 硬超时
（commit 2d262b6），但**还有多个相同模式的调用点没修**。

**问题模式**：项目里存在两套独立的 LLM 调用路径：

**模式 A（受保护）**：通过 OperationPool → 每个 handler 都被
`asyncio.wait_for(handler(...), timeout=120s)` 包裹。
- `do_something` ✅
- `generate_message` ✅
- `remember_conversation` ✅

**模式 B（不受保护）**：直接 await llm_client.generate(...) 或类似——
**没有 asyncio 层的硬超时**。只靠 httpx 的 read_timeout / pool_timeout
等，但实测 httpx timeout 在 SSL handshake / pool 等待 / 半开连接等
情况下会失效。

**已知模式 B 调用点**（需要补 timeout）：

1. ~~`tools/run_variant_suite.py:874` `_process_ops_hook` 的 `maybe_reflect`~~
   → 已修（commit 2d262b6）
2. `synthetic_socio_wind_tunnel/memory/reflection.py:reflect` 内部对
   `llm_client.generate(prompt)` 的直接 await
3. `synthetic_socio_wind_tunnel/memory/importance.py:score_importance`
   对 LLM 的直接 await
4. `synthetic_socio_wind_tunnel/agent/planner.py:replan` 的 LLM 调用
5. `synthetic_socio_wind_tunnel/data_loader/lanecove.py` 里
   `_generate_life_history_for_one` / `_generate_identity_text_for_one`
   的 await（cache MISS 路径才走，HIT 不走 → 当前 D2 没踩，但理论上有
   风险）
6. `tools/prewarm_setup_content.py` 通过的同样路径

**统一修法**：

```python
# 推荐模板
import asyncio
try:
    result = await asyncio.wait_for(
        llm_client.generate(prompt, ...),
        timeout=60.0,  # 或基于 tier 调整
    )
except asyncio.TimeoutError:
    logger.warning("LLM call timed out, using fallback")
    result = fallback_value
```

**或者重构方向**（更彻底）：

让所有 LLM 调用强制经过一个统一的 `bounded_llm_call(client, prompt,
timeout)` wrapper，无 timeout 不允许调。可以是装饰器或 mixin。

**优先级**：高。
- 这次 D2 已经踩 6 次了，单次 cost ~40 min wall
- 不修下次跑 publishable 同样要踩
- 工作量小（~30 行代码 × 5 调用点 = ~150 行 + 单测）

**估工**：半天到一天。

**Owner**：未指定。

---

## 1.11 `--resume` 不保留 run_metrics（设计漏洞）

**状态**：✅ 已实施（snapshot schema v2 加 `tick_metrics_recorder_state`；
schema v3 又加 `dialogue_service_state`）。`TickMetricsRecorder` 已有
`to_snapshot_state` / `from_snapshot_state`；`MultiDayRunner._write_snapshot`
和 `_write_final_snapshot_on_graceful_stop` 都已 wired；`restore_into`
已 from_snapshot_state。round-trip + append-after-resume scenario 在
`tests/test_metrics_recorder.py::TestRecorderSnapshotRoundtrip::test_resume_appends_to_existing_buckets`。
openspec `harden-worker-resilience` 形式化进 `tick-level-resume` spec。

**记录时间**：2026-05-18

**背景**：D2 attempt 4 跑下来 baseline seed 42 / 43 完成后发现，
`seed_42.json` final file **只覆盖 resume 之后那段天数**，
day 0-9（原始 worker 跑的部分）的 per_day_summaries / 累积 metric 全
丢失。

**问题原因**：
- tick-level-resume capability 设计时 snapshot 只覆盖 mutable state
  （Ledger / AgentRuntime / MemoryService / AttentionService）
- `run_metrics`（per_day_summaries / TickMetricsRecorder accumulated
  state）NOT included in snapshot
- Resume 后 MultiDayRunner 用 fresh empty TickMetricsRecorder 开始累积
- 原始 worker 已写的 day_X.partial.json 也没被 merge
- 最终 seed_X.json 只反映 resume worker 跑的天数

**影响**：
- D2 attempt 4 所有被 kill+resume 过的 seed 的最终 metric 都是
  partial（4 个完整 + 8 个 partial = 8 个 seed × 4 variant 里有 8 个
  partial 数据）
- 必须从 WAL 后处理才能拿到 full 14-day metric
- WAL 数据完整（per-tick 写），所以"can be recovered"

**修法选项**：

### 方案 A：snapshot 把 run_metrics 也带上（推荐）
- 改 `SimulationCheckpoint` 加 `run_metrics_state: dict` 字段
- TickMetricsRecorder 加 `to_snapshot_state()` / `from_snapshot_state()`
- Resume 时把累积的 per_day_summaries 灌回 recorder
- 工作量：~2-3 hr
- 风险：低（既有的 snapshot round-trip 测试模式可复用）

### 方案 B：终态 aggregation 从 WAL 重建
- 写 `tools/aggregate_d2_from_wal.py` 后处理脚本
- 遍历 worker_*.log + wal.jsonl + final seed_X.json
- 用 WAL 的 per-tick 数据重建 per_day_summaries / trajectory_deviation /
  encounter density 等
- 工作量：~半天
- 风险：WAL 缺少某些字段（如 trajectory_deviation_m 计算需要 agent
  position 而 WAL 只记 encounter_count），可能要再从 snapshot / position
  data 补
- 当前 D2 必须走这条路（A 改完了对当前数据无影响）

### 方案 C：禁止 mid-run resume on metric-sensitive run
- 跑 publishable 时强制 worker 跑到底不 kill
- 限制：内存压力大 / day-end deadlock 时没法干预

**推荐做 A**（下次 publishable run 之前），同时本次 D2 走 B 抢救数据。

**优先级**：高。
- 下次 publishable 必踩
- A 工作量小（半天），ROI 极高

**Owner**：未指定。

---

## 1.12 DialogueService 持久化 — 答辩 narrative 输出必需

**状态**：✅ 已实施（snapshot schema v3 加 `dialogue_service_state`；
`DialogueService.to_snapshot_state` / `from_snapshot_state` + harden-worker-resilience
的 `evict_old_dialogues` rolling cleanup 一起；round-trip test 在
`tests/test_dialogue_service_eviction.py::test_snapshot_round_trip_preserves_summaries`
+ `tests/test_subsystem_snapshot.py`）。

**记录时间**：2026-05-18

**背景**：D2 attempt 4 narrative 数据调查发现两个串联问题：

**问题 A**（已修，commit 8941383）：MultiDayRunner 没传 memory_service →
snapshot 的 memory_store_state 永远是空 → 所有 MemoryEvent 包括
kind="conversation" 的对话摘要丢失。**仅影响 resume 跨界的数据保留**。
一行修。

**问题 B**（本条 backlog）：**DialogueService 完全没有持久化机制**。
即使 A 修了，conversation 的"summary"留下来了，但 Dialogue 对象本身和
DialogueMessage 列表（即真正的"对话原文"）仍只活在 Python 进程内存，
worker 退出就消失。

```python
# 当前 DialogueService 内部状态:
#   _dialogues: dict[str, Dialogue]
#     每个 Dialogue 包含 messages: list[DialogueMessage]
#       每条 DialogueMessage 有 speaker_id / content / tick
#
# 持久化: 没有 to_snapshot_state / from_snapshot_state
#         没有任何 .json 写盘
# 后果: 答辩 narrative panel "李建平跟王伟说..." 这种引用没法做
```

**修法**：

### A. 加 DialogueService.to_snapshot_state() / from_snapshot_state()
- 序列化 _dialogues dict 到 JSON
- DialogueMessage 是 @dataclass 容易序列化
- restore 时重建 Dialogue 对象
- 工作量：~1 hr

### B. 集成进 SimulationCheckpoint
- 在 state_snapshot.py 加 `dialogue_service_state: dict`
- 在 multi_day.py:599 处的 SimulationCheckpoint() 构造里加：
  ```python
  dialogue_service_state=(
      dialogue_service.to_snapshot_state()
      if dialogue_service is not None else {}
  ),
  ```
- restore_into 路径加 dialogue_service.from_snapshot_state(...)
- 需要把 dialogue_service 传到 MultiDayRunner（跟 memory_service 同模式）
- 工作量：~1 hr

### C. 单测
- 类似 tick-level-resume 的 round-trip test:
  序列化 → JSON → 反序列化 → 等价
- 工作量：~1 hr

### D. fitness audit probe
- 加到 audit_tick_level_resume.py 检查 DialogueService 有
  to/from_snapshot_state
- 工作量：~30 min

**总估工**：~3-4 hr

**优先级**：高
- 用户答辩 narrative 是 D2 attempt 4 之外的明确产出物
- 没有这个，narrative panel "agent 之间的故事" 无法写
- 必须在下次 publishable run 之前完成

**实施约束**：
- 不影响今天 D2 跑（imports 已冻结）
- 但 D2 跑完后立刻做，下次 publishable 跑就能拿到完整 dialogue 内容

**Owner**：未指定。

---

## 1.13 fallback-rate budget + run_metrics 暴露（"沉默灾难"防护）

**状态**：✅ **完整落地**（2026-05-20 Part 2 收尾）。已落地：
- `synthetic_socio_wind_tunnel/run_resilience/llm_health.py::LLMHealthTracker`
- `AllKeysOpenError` 不再被吞（reflection / importance / planner 各 except 分支）
- per-call `record_fallback` / `record_success` 收集
- `FallbackBudgetExceeded` 阈值 raise
- `DayRunSummary` 加 `llm_fallback_pct` / `llm_total_samples` /
  `all_keys_open_count` 字段（per_day surface）
- `RunMetrics.extensions` 加 `max_llm_fallback_pct` / `avg_llm_fallback_pct`
  / `all_keys_open_total` (per-run roll-up via run_variant_suite)
- `SuiteAggregate` 加 `max_llm_fallback_pct` / `avg_llm_fallback_pct` /
  `high_fallback_warning` (cross-seed roll-up via aggregator)
- **2026-05-20**: `ContestRow` 加 `high_fallback_warning` /
  `max_llm_fallback_pct` 字段；`build_contest_report` propagate +
  `notes` 拼接警告字串。`report.md` write_markdown 每个 variant
  emit "**⚠️ high LLM fallback X% — data may be fallback-template**"
  独立一行（与 `degraded_preliminary` 警告并列）。Regression tests:
  `tests/test_llm_fallback_visibility.py::test_contest_row_propagates_high_fallback_warning`
  / `test_report_md_emits_high_fallback_line` /
  `test_contest_row_legacy_aggregate_no_warning`

**记录时间**：2026-05-19

**背景**：D2 attempt 4 (2026-05-18) 出现"沉默灾难"——DeepSeek 余额耗尽
触发 402 cascade，但 `do_something` / `reflect` / `importance` 三个
handler 的设计是 **graceful fallback, never raises**：

```python
# synthetic_socio_wind_tunnel/agent/operations/handlers/do_something.py:166
"""Failures fall back deterministically — never raises."""
try:
    raw = await llm_client.generate(prompt, ...)
except Exception:
    action = _fallback_action(args)  # → {"action":"wait"} 或第一个候选
    return OperationResult(success=True, payload={**action, "fallback": True})
```

结果：4 个 worker 在 100% fallback 模式下"跑得很好"——
- tick 推进、commit 成功、encounter 计数正常
- 但每个 agent 决策都是模板 fallback，没有任何 LLM 真实决策
- run 看似进度正常，实际产出"确定性 wait-everyone sim"垃圾数据
- 4 小时没人发现，浪费机器 + Volces 钱

**根因**：fallback **逐条** 是对的（单点 LLM 抖动不该杀 1000-agent run），
但 **缺三层 safety net**：

| 层 | 该做的 | 当前 |
|---|---|---|
| handler | per-call fallback | ✅ 已有 |
| **aggregator** | **rolling window fallback-rate abort** | ❌ 没有 |
| **run metrics** | **per-day fallback% 入账 + 在 contest.json 可见** | ❌ 没有 |
| circuit-breaker | 全开时立即 raise，不被吞 | ❌ 被 `except Exception` 吞 |

**理想方向**（~50 行改动）：

1. **MultiDayRunner 聚合 fallback rate**——OperationResult.payload.fallback
   字段已存在；on_tick_end 聚合：rolling 5 min 窗口
2. **soft abort threshold**：rolling fallback-rate > 20% 持续 N 个 tick
   → 写 partial → raise `FallbackBudgetExceeded` → 上层 SIGTERM 自身
3. **每个 per_day_summary 加字段**：
   ```python
   {"day_index": 0, ..., "llm_fallback_pct": 2.3, "circuit_breaker_open_count": 0}
   ```
4. **contest.json + report.md 引用**：variant 总 fallback% 显著（>5%）
   时标 warning，避免下次又"看起来跑完了"
5. **AllKeysOpenError 不再被 fallback 吞**——专门 catch 这个 exception
   raise 出去，因为 8 keys 全开是结构性故障不是单点抖动

**为什么不立即做**：今天事件已经发生、损失已发生；先用
`tools/audit_llm_health.py` 做**外部** monitor 弥补。代码内部的
fallback-budget 是下一个 publishable run **之前** SHALL 做完，不能
再让灾难无声跑 4 小时。

**优先级**：高 — 下次 publishable 跑前必做。

**触发条件**：当下次 publishable 跑（D2 attempt 5 或 D3）排期时立刻做。

**估工**：~50 行代码 + 单测 + 集成测，约 2-3 小时。

**Owner**：未指定。

**关联事件记录**：
- D2 attempt 4 的 16+ 小时"沉默 fallback" 损失（2026-05-18 → 19）
- 用户原话："fallback 是什么设计，LLM没有响应应该直接报错，为什么继续跑下去了呢？？"
- 给出的答辩："设计假设是少量 fallback 不影响结果，但根本没有给 fallback
  一个上限——这是 bug"

---

## 1.14 单 worker 多核并行化 — 解 Python GIL 单线程瓶颈

**记录时间**：2026-05-19

**背景**：D2 attempt 5 (2026-05-19) 跑下来发现，**单进程单线程**是真正
的瓶颈。具体观察：

- 机器：15 core Apple Silicon, 48 GB RAM
- 跑 4 workers (hp/pf × seed42/43)
- 单 worker CPU：99% (hp, CPU-bound) / 53-55% (pf, LLM-network-bound)
- **机器整体 CPU：70% IDLE** —— 11 个核空闲
- Load average：4.55 = 大概 4 核在跑

结果：每个 worker 大概用 1 核（asyncio 单线程 + Python GIL）；tick 速度
30-50s/tick；14 天 publishable 单 worker 要跑 8-15 小时。**机器有 11 个
核完全没用上**。

具体瓶颈点（推测，需 profile 确认）：
- `OrchestratorService.tick()` 里 1000 agent × 1000 agent encounter
  detection = 0.5M 对每 tick = O(N²) Python 循环
- `MemoryService.retrieve(top_k)` 每个 do_something 触发，按 importance
  × relevance × recency 排序
- Pydantic 模型 serialize（每 tick 各种 Event/Result）
- WAL JSON 写盘（小，可忽略）

**理想方向**：让单 worker 用上多核。两条思路：

### 思路 A：算法 + 数据结构优化（中等改动，最大 ROI）

- **Encounter detection 用空间索引**：1000 agents × O(N²) → O(N log N)
  或 O(K) per agent。R-tree (rtree pkg) / kd-tree (scipy.spatial.cKDTree)
  根据 agent.position 建索引；每 tick 只查 within-radius pairs (10-50m)。
  实测可能 100x 提速。
- **Memory retrieval 用向量近邻**：embedding 缓存 + scipy.spatial /
  HNSW (hnswlib)。可能 5-10x。

工作量：1-2 周。风险中等（要保持 encounter 语义不变，单测 + e2e 对比）。

### 思路 B：进程级并行（hot path 卸到 ProcessPoolExecutor）

asyncio 主进程不动，但 hot path 卸到子进程池：

```python
# 现在：
async def tick():
    encounters = compute_encounters(agents)  # 单线程 O(N²)
    ...

# 改：
async def tick():
    loop = asyncio.get_event_loop()
    encounters = await loop.run_in_executor(
        process_pool,
        compute_encounters_pure_data,  # 必须 pickle-able
        agent_positions_snapshot,
    )
```

注意：必须 `ProcessPoolExecutor`（不是 ThreadPoolExecutor），因为线程
被 GIL 卡。子进程之间数据传输（pickle agent positions × 1000）每 tick
1-5 ms 开销，可接受。

工作量：3-5 天。风险：state 必须能 cheap-pickle；agent runtime 不能
in-place mutate（已经分离了大部分）。

### 思路 C：Numpy/Numba JIT 编译 hot path（最少代码改动）

把 encounter detection 改成 numpy 向量操作 + numba `@jit`：

```python
@numba.jit(nopython=True, parallel=True)
def find_encounter_pairs(positions: np.ndarray, location_ids: np.ndarray,
                         radius: float) -> np.ndarray:
    # numba 释放 GIL + 自动多核 SIMD
    ...
```

工作量：~1-2 天（要把 encounter 抽成纯函数）。风险：numba 对 dict /
str 不友好，可能要数据结构转换。

### 思路 D：Cython 编译 Python hot path

最重的改动，最大确定性的 speedup（2-5x）。工作量 1-2 周。

**推荐顺序**：思路 A 先（算法层最大收益）→ 思路 B 补（process pool
卸 hot path 多核）→ 思路 C 兜底（如果 A+B 不够 + numba 能接更细的优化）。

## 影响估计（假设 A + B 完成）

- 单 worker tick 时间：35s → 5-10s（5-7x 提速）
- 单 seed 14-day publishable run：12 hr → 2-3 hr
- 机器内存：单 worker 5 GB → 子进程池另加 ~500 MB
- 总跑 β=4 publishable (4 seed × 4 variant = 16 worker)：原本需要 16 hr
  × 多 batch（48 hr）→ 8 hr 一次跑完

**优先级**：高 — 长期 ROI 巨大。**但不紧急**：当前 D2 attempt 5 跑得动，
等下次 publishable 排期前的间歇做。

**触发条件**：
1. D2 attempt 5 跑完 + 分析完，回过头有 1-2 周空窗时；OR
2. 决定上 D3 (β≥10) 之类大规模实验，必须提速；OR
3. 答辩后整理代码阶段。

**估工**：
- 思路 A（空间索引）：2-3 天 + 单测
- 思路 B（process pool）：3-5 天 + e2e
- 总：~1 周 + 0.5 周对比测试

**Owner**：未指定。

**关联**：
- [[backlog 1.7]] 多 worker 内存优化 — 内存压力解决思路，与本条互补
- [[backlog 1.8]] baseline-prefix-share — wall time 优化的另一条路

---

## 2. ReAct-style LLM 决策架构（替换 hint pre-fill）

**记录时间**：2026-05-17

**背景**：D2 attempt-4 pre-launch audit 揭示 `recent_memory_hint` /
`nearby_hint` / `candidate_destinations_hint` 三个字段都是死代码。我们当场
fix 成"在 schedule do_something / generate_message 时 lazily refresh"。
这是**功能修复**，不是架构修复。

**架构层面的问题**：整个 "hint pre-fill" 模式本身就不"像人"——
- 真实人类做决定不靠"someone hand me a list of recent memories"
  → 是**联想触发**：看到 Plaza 才想起上次在 Plaza
- 真实人类的"附近的人"不靠 dict lookup
  → 是**视觉感知**：转头看到旁边坐着人
- 真实人类的"可去的地方"不靠 enumerate list
  → 是**目标导向**：想吃饭 → 想到餐厅，想散步 → 想到公园

**理想方向**：ReAct-style LLM tool calling
- LLM 在做决定时**有工具可调**：
  - `memory.retrieve(query)`：按需查记忆
  - `perception.scan_nearby()`：扫描周围
  - `location.search(goal_keyword)`：按目标搜地点
- LLM **自己决定**要不要查、查什么、查多深
- 像真实"心智过程"——查询是认知行为的一部分，不是 prefilled context

**优先级**：低。这是架构重构，不是 bug。当前 lazy-fill 路径质量已经够 D2。

**触发条件**：
1. 答辩之后；OR
2. 决定上更大规模研究（β=30+ run）且想提升 LLM 决策真实性时

**估工**：3-5 天。涉及：
- OperationPool handler 重写（do_something / generate_message 改成可循环
  调用工具）
- LLM provider 选 tool-calling 友好的（DeepSeek v4 / Claude / GPT-4 都支持）
- prompt 模板大改（function-calling schema）
- 单元测试 + 端到端验证
- 性能：每个 do_something 现在 1 个 LLM call，ReAct 模式可能 3-5 个，
  成本上升

**Owner**：未指定。

---

## 1.16 encounter event eviction 误杀所有 encounter（tick 语义混用）

**记录时间**：2026-05-20

**严重级别**：🚨 BLOCKING for thesis-relevant analysis（encounter 是
phone_friction / hyperlocal_push 主线 H_pull / H_info 的 dependent
variable）

**Bug**:
2026-05-20 04:00 实测 publishable resume worker 健康跑 day 12（25+ 分钟，
1000/1000 commits, 835 distinct destinations, 真 LLM-driven actions），
但 `memory_store_state.events_by_kind` **encounter=0**。

精确根因：

- `orchestrator/service.py:260` 主 tick 循环：
  `for tick_index in range(num_ticks):` 其中 `num_ticks = ticks_per_day
  = 288`，所以 `tick_index ∈ [0, 287]` **per-day**
- `memory/service.py:521` `tick = tick_result.tick_index`，传给
  `MemoryEvent.tick` 字段 → encounter event 的 `tick` 字段是
  **per-day 0-287**
- `memory/store.py::evict_cold_encounter_events(before_tick)`：
  `if ev.kind == "encounter" and ev.tick < before_tick`
- `multi_day.py` 计算 cutoff：`(day_index - grace) * ticks_per_day`
  → day 12 grace 2 → cutoff = **2880** (global tick)
- **`ev.tick ∈ [0, 287] < 2880` 永远成立** → 每次 snapshot pre-write
  evict + day_end evict 都把全部 encounter events 清空
- action / life_history / shared_memory 不受影响（eviction 只
  filter `kind=="encounter"`）

**影响范围**：
- 所有 `enforce-worker-rss-cap` (2026-05-19) 之后跑的 publishable run
- encounter 检测 (WAL `encounter_count`) 不受影响 — 这是 orchestrator
  层面统计，没经 memory_store
- memory_store 里 encounter 用于 LLM context retrieval — 这部分 LLM
  看不到 historical encounter，会影响"上次见过谁"类型的决策
- 任何下游 metric 通过 `memory_store.events_by_kind("encounter")` /
  `retrieve(kind=encounter)` 读 encounter 的 → 全是 0

**为什么测试没抓到**：
- `tests/test_memory_store_encounter_eviction.py` 用 hand-crafted
  events with explicit small `tick` values（0, 10, 200）+ explicit
  `before_tick=cutoff`。测的是 **eviction 机制本身**（"if tick <
  cutoff → 删"），**不测 tick 语义是否与调用方一致**。
- 同样 pattern 跟 `_self_rss_mb` ru_maxrss bug、跟
  `comprehensive-runtime-instrumentation` wiring gap 一模一样：
  **mock-level test 保证 API 契约，integration test 缺失**

**修复方向**（3 选 1，待 design 讨论）：

(A) 让 encounter event 存 `tick_global`
- 改 `MemoryService.process_tick` 内部 encounter 写入时：
  `event = MemoryEvent(tick=day_index * ticks_per_day + tick, ...)`
- 简单，但侵入 process_tick 一处
- ⚠️ 影响 retrieve by tick — 但 retrieve 通常按 tag/kind/agent，
  不按 tick

(B) Eviction 用 `day_index` 比较而不是 `tick`
- `evict_cold_encounter_events(before_day_index=N)`：
  `if ev.kind == "encounter" and ev.day_index < before_day_index`
- 改 eviction API + caller，不动 MemoryEvent
- 简单，语义清晰

(C) Eviction 内部计算 `tick_global` on the fly
- `ev_global = ev.day_index * ticks_per_day + ev.tick`
- `if ev.kind == "encounter" and ev_global < before_tick`
- 需要把 ticks_per_day 传入 evict 方法
- 改动小，API 不变

**推荐**：**(B)** —— `day_index` 比较语义最清晰，符合 cold-prune 的
人类直觉（"删 grace_days 之前的"）。`before_tick` 参数本来就是 derived
from day_index，不如直接用 day_index。

**测试盲点修复**：
- 加 e2e test：跑 dev smoke 50 agent × 4 day，**直接读 memory_store
  里 encounter 数量**，断言 day 3 时 day 0-1 的 encounter evicted 但
  day 2-3 的 encounter **存在**（不是 0）
- 这种 test 才会捕捉 tick 语义错配

**优先级**：高。当前 publishable run 数据 encounter 维度无效。
**触发条件**：next publishable resume / 新 cell spawn 之前必须修。
建议下个 OpenSpec change `fix-encounter-eviction-tick-semantic`。

---

## 1.15 正式 publishable run 前的自动化 preflight checklist

**状态**：✅ 已实施（2026-05-20）。`tools/preflight_publishable_spawn.py`
跑 6 个检查 (python_venv / env_vars / disk_free / stale_worker /
swap_pressure / instrumentation_smoke) + 可选 resume_strategy（带
suite_dir+seed）。其中 instrumentation_smoke 跑 3-4 秒真 dev smoke +
inspect 真 events.jsonl，断言 7 个 required PHASE events 全部 fire。
exit 0=clean, 1=blocker, 2=warnings only。Regression test in
`tests/test_preflight_publishable_spawn.py`（3 个 test 含 phase-gap
检测的负向 case）。

**记录时间**：2026-05-20

**背景**：2026-05-20 凌晨实测 publishable resume 暴露多个"应该提前发现
但跑起来才发现"的盲点：
- snapshot 反序列化 35GB 峰值不在任何优化覆盖范围（`prune-before-
  snapshot-write` 已修，但当时还没意识到）
- `_self_rss_mb` 用 ru_maxrss 而非当前 RSS 的 bug（spawn 后才发现）
- 埋点桩点缺失（SETUP_START / SNAPSHOT_LOAD_START / TICK_LOOP_START
  这几个 phase event 没实际 wire 到代码里，spec 写了但 impl 漏了）
- 3 个观察通道（probe TSV / tail_memstat / summarize watch）需要手动
  各开一次 nohup，容易漏

每次 spawn 是真 LLM cost ($ + 时间)，少了任一个检查可能浪费整个 spawn
窗口。需要一个**自动化 preflight script**，跑过且全绿才允许 spawn。

**理想方向**：

`tools/preflight_publishable_spawn.py <suite_dir> <seed> <variant>`：

1. **静态检查**
   - 当前 commit 是否在 main + clean
   - 关键 env vars 已设（RSS_RESTART_MB, MEMORY_EVENT_EVICT_GRACE_DAYS,
     SNAPSHOT_PRUNE_BEFORE_WRITE, INSTRUMENTATION_OUTPUT_DIR）
   - `.venv/bin/python` 存在 + psutil 可 import
2. **Cell state 检查**
   - 跑 `audit_resume_strategies.py` 自动选 `--resume-strategy`
   - 没残留 worker（grep PID + check WAL age）
   - LaunchAgent 状态（registered 或 not，by intent）
3. **资源 capacity 检查**
   - 磁盘 free > 30GB
   - swap_pressure 不在 high
   - DeepSeek API 网络可达（HTTP HEAD ping）
4. **埋点桩点检查**（关键，2026-05-20 教训）
   - 跑一个 5-second `--mode=dev --num-days=1 --agents=10` smoke
   - verify 这个 smoke 输出的 events.jsonl 含**所有 9 个 PHASE 事件**
     按 spec 顺序：PROCESS_START → SETUP_START → SETUP_DONE →
     [SNAPSHOT_LOAD_*] → TICK_LOOP_START → DAY_START → DAY_END → EXIT
   - 任一缺失 → fail 退出，spawn 拒绝
5. **观察通道一键开**
   - 输出三条 `nohup ... &` 命令一次性 spawn 所有 watcher，return PID list
   - 或直接 spawn 起来，让 user 复制 tail 路径
6. **Spawn 命令生成**
   - print 出完整 nohup spawn 命令（带所有 env vars），让 user 复制粘贴

**优先级**：中。下次 publishable resume 前应该有。当前 CLAUDE.md
"正式 publishable cell spawn 步骤"段是文档形式，但仍然手动，容易漏一步。

**触发条件**：
- 下次准备 spawn publishable cell 时（最迟）
- 或：开始系统性多 cell 重跑时（每个 cell 都要 spawn，自动化收益翻倍）

**估工**：1 天。
- preflight_publishable_spawn.py 主脚本（已有 audit + summarize 工具可复用）
- "smoke + verify all 9 phase events fire" 这条需要先修 instrumentation
  桩点缺失（独立小 OpenSpec change，估 2-3 小时）
- 端到端 + dry-run + actual spawn 测试

**关联**：
- [[runtime-instrumentation]] 2026-05-20 不变量段（要补 5 个未 wire 的
  phase event：SETUP_START / SETUP_DONE / SNAPSHOT_LOAD_START /
  SNAPSHOT_LOAD_DONE / TICK_LOOP_START / DAY_START / DAY_END）
- [[audit_resume_strategies.py]] 2026-05-20 工具，preflight 复用之

**Owner**：未指定。

---

## 1.16 snap-after-tick 语义 — resume 1-tick 重叠 ✅ RESOLVED 2026-05-21

**状态**：closed by `resume-rng-state-determinism` openspec change
(2026-05-21). 实施方案 B：`Orchestrator.run(start_tick=N)` 参数 +
`SimulationCheckpoint.tick_index_in_day` 字段 + `MultiDayRunner` 在第一
个 resumed day 传 `start_tick = snap.tick_index_in_day + 1`。E2E test
`TestMidDayResumeDeterministic::test_resume_from_mid_day_snap_matches_fresh`
验证 fresh 2-day vs mid-day-snap-resume 终态 byte-equal。

**原始记录**（保留 for 历史）：

**触发**：写 `test_resume_byte_identical_to_fresh` 时发现 fresh 2-day vs
resume (1 day → snap → 1 day) 结果差 5 分钟（1 tick）。

**根因**：`_on_tick_end_resume_hook` 在每个 tick **执行完** 触发，snap
fire 条件 `tick_global % every_ticks == 0`。当 `every_ticks=288`：
- snap 在 `tick_global=288` 触发 = day 0 全部 288 tick + day 1 第 1 个
  tick 完成 = ledger.current_time = start+1d+5min
- snap 元数据：`day_index=1, tick_index=288`
- resume restore：ledger 回到 start+1d+5min，effective_start_day=1
- resume 跑：`for day_index in range(1, 2)` → 跑 day 1，
  `Orchestrator.run(day_index=1)` 从 day 1 tick 0 开始**重新跑 288 tick**
- 终态：start+1d+5min + 288*5min = start+2d+5min
- Fresh 终态：start + 576*5min = start+2d
- **diff = 5min（1 tick 双重执行）**

**影响**：跨 worker resume 后下游分析的 timestamp 会偏 1 tick；publishable
14-day 跑里如果中途 resume N 次累计偏移 N tick = 5N 分钟。**实测 D2
attempt 6 同源 sim-time drift 部分原因即此**（snap mtime 在 reboot 后
变 stale → watchdog 误判 → SIGUSR1 → 多次 resume）。

**修复方案**（择一）：
- **A. 修 snap-fire timing**: 改成 `_on_tick_start_resume_hook`，snap
  fires **before** tick 执行 → snap 内 ledger 是 tick boundary 状态
  → resume 不重叠
- **B. 引入 tick-in-day resume**: snap 内增 `tick_in_day_at_snap`；
  Orchestrator.run 接受 `start_tick=N` 参数，跳过 0..N-1 tick
- **C. snap 文件本身记录 "已完成 N tick"，resume 把 day 跑 (288-N) tick**

A 最简单但 snap 语义改变（破坏现有 snap 读取兼容）。B 最干净但需要
改 Orchestrator.run 签名。

**Owner**：未指定，需 design review。

**关联**：[[resume-rng-state-determinism]] 2026-05-21 spec —
确认 RNG 部分已正确 round-trip，但 1-tick 偏移仍是 product-level 不变量
("断点续跑 == 正常跑") 的最后一个 gap。

## 1.17 watchdog stale threshold 默认对 day_end transition 太短（2026-05-21 实测）

**触发**：seed 43 publishable run 2026-05-21 05:46 watchdog 把 baseline WAL 标 STALE (age=331s > 300s 阈值)，但 baseline 实际正在 day_end transition：
- tick 287 写完 (05:41:07)
- memory.run_daily_summary 跑 500 protag × LLM call (concurrency~30, p50 ~11s)
- 总耗时 ~3-5 min daily_summary + ~3 min plan gen
- 期间 WAL 完全无写入（因为没 tick 推进）

→ **300s / 420s 阈值在 day_end 窗口必然误判**。如果 watchdog confirm 阶段（额外 60s 等待）撑过去就 SIGUSR1 → 触发 `sigusr1-graceful-stop-corruption` 风险 + 丢失 tick 277-287 工作。

**修复方案**（择一）：

**A. 提高 stale_secs 默认值**：从 420s → 900s (15 min)。简单但牺牲常规 hang detection 速度（25 min → 30+ min 才报）。CLAUDE.md spawn 模板里我已经更新到 900s 用于本次跑。

**B. 智能 stale 判定**：watchdog 不只看 WAL mtime，还看 `llm.jsonl` mtime。如果 LLM 最近 60s 内有 call → worker 真活着，不算 stale。这个最 robust。需要改 watchdog 工具。

**C. 加 events.jsonl heartbeat**：worker 在 daily_summary / plan_gen 等长阶段每 60s 写一个 `HEARTBEAT` event。watchdog 改成 events.jsonl mtime 判定。需要 instrumentation + watchdog 协同改。

**D. 区分 phase**：worker 在 events.jsonl 写 `DAY_END_START / DAY_END_DONE` phase event。watchdog 检测到 DAY_END_START 后允许长 stale 直到 DAY_END_DONE。最干净但需要 wire 新 phase event。

**短期对策**：CLAUDE.md spawn 模板 + `tools/preflight_publishable_spawn.py` 推荐值改 `--stale-secs 900 --confirm-secs 120`。本次跑已经手动改了。

**关联**：
- [[sigusr1-graceful-stop-corruption]] 2026-05-19 不变量 — 误 SIGUSR1 会污染数据
- [[monitor-as-control-plane]] 2026-05-19 不变量 — watchdog 不持有 termination 决策权（但本工具是个例外，因为它跑 auto-remediate）

**Owner**：未指定。下次 publishable run 之前必须有 A 兜底（B/C/D 是长期改进）。

## 1.18 `_generate_plans_for_day` 没 asyncio.wait_for 兜底（2026-05-21 audit 发现）

**根因**：`MultiDayRunner._generate_plans_for_day` (multi_day.py:1049-1078)：

```python
async def _one(agent):
    plan = await self._planner.generate_daily_plan(...)  # NO wait_for!

async def _all():
    await asyncio.gather(*(_one(a) for a in agents_by_id.values()))

asyncio.run(_all())
```

**风险**：500 个 plan generation task 用 `asyncio.gather` 跑 — 如果其中 1 个 LLM call hang（httpx half-open TCP / DeepSeek 长尾），**整个 gather 阻塞等所有任务完成**，工作进入静默死等。

**违反不变量**：CLAUDE.md `1.9 所有直接 LLM call 加 asyncio.wait_for 硬超时兜底 2026-05-19` —
> 任何直接 LLM call SHALL 用 `asyncio.wait_for(...)` 兜底，避免 D2 attempt 5 那种 worker silent hang

`_generate_plans_for_day` 漏修。同时还需检查类似 unguarded await 的所有位点。

**触发条件**：4 worker 同时 day_end → 500 plan generation 同时跑 → DeepSeek 服务端在某个 task 上 silent drop → asyncio.gather 卡住。

**2026-05-21 publishable seed 43 run 实测**：跑了 100 min 没 hang（只是 ~5-10 min day_end slow window）— 但风险窗口实际存在。

**修复方案**：

```python
async def _one(agent):
    try:
        plan = await asyncio.wait_for(
            self._planner.generate_daily_plan(
                agent.profile, date=current_date.isoformat(),
                carryover=carryover,
            ),
            timeout=90.0,  # 单 plan 最多 90s，超时用 fallback profile-only plan
        )
    except asyncio.TimeoutError:
        logger.warning(f"plan gen timeout for {agent.profile.agent_id}; "
                       "falling back to template plan")
        plan = self._planner.build_template_plan(agent.profile, date=current_date.isoformat())
    agent.plan = plan
```

**Owner**：未指定。**下次 publishable run 前必修**（这次 seed 43 跑得过没 hang，下次未必）。

**关联**：
- [[1.9 所有直接 LLM call 加 asyncio.wait_for 硬超时兜底]] 2026-05-19 不变量
- [[harden-worker-resilience]] 2026-05-19 spec — direct_llm_timeout_guard 5 个位点全 wait_for 验证 test
- backlog 1.17 watchdog stale 阈值 — 即使 hang 发生，stale 检测应该兜住 30 min（已升 3600s 兜底）


## 1.19 `build_suite_aggregate` 在 graceful_stop 0 RunMetrics 时崩（2026-05-21 实测）

**触发**：seed 43 baseline RSS 9905MB > 6000MB cap at tick 350 → graceful_stop 写 partial + snapshot → MultiDayRunner 返回 truncated result (0 RunMetrics)。然后：

```python
File "tools/run_variant_suite.py", line 1988, in main
    aggregate = build_suite_aggregate(runs, variant_metadata=...)
File "synthetic_socio_wind_tunnel/metrics/aggregator.py", line 105
    raise ValueError("build_suite_aggregate requires at least one RunMetrics")
```

→ run_variant_suite crashes at end-of-script aggregate step. **worker process exits non-zero**，外部需要手动重启（或 LaunchAgent / resume_publishable.py 自动接管）。

**问题**：`build_suite_aggregate` 假设 graceful_stop 也产生 RunMetrics，但实际上 graceful_stop 路径 `seed_N.json NOT written, partials preserved for resume` — 整个 variant 还没完成，aggregate 应该 skip。

**修复方案**：

```python
# tools/run_variant_suite.py around line 1988
if not runs:
    print("[suite] no completed runs (graceful_stop or all failed); "
          "skipping aggregate. Use --resume to continue.", file=sys.stderr)
    sys.exit(0)  # graceful_stop 本身不算 fail，exit 0 让 outer launcher resume
aggregate = build_suite_aggregate(runs, ...)
```

或者 `build_suite_aggregate` 自己处理 empty list 返回 empty aggregate.

**Owner**：未指定。下次 publishable run 前修，否则 RSS auto-restart 每次都需要手动重启 worker（loss-of-automation）。

**关联**：
- [[backlog 1.7 B]] auto-restart on RSS — 触发条件正常
- [[sigusr1-graceful-stop-corruption]] — 不写假 seed_N.json 部分工作正常
- 但 build_suite_aggregate 误把 graceful_stop 当 "all variants failed" 抛错

## 1.20 cold-prune evict 实际 evict=0 events，snapshot 不缩 (2026-05-21 audit 发现)

**触发**：seed 43 baseline-prefix day 3 end EVICT event 显示：

```json
{"kind":"EVICT","before_day_index":1,"events_evicted":0,
 "memory_store_total_before":4426274,
 "memory_store_total_after":4426274}
```

evict 调用参数对（GRACE=2 at day 3 → before=1，应 evict day 0 encounter events）但实际 **events_evicted=0**。memory_store 4.43M events 一个没动。

**对架构的后果**：
- backlog 1.6 (snapshot-resume-ram-peak) 表面"已通过 cold-prune 解决"实际无效
- snapshot 文件大小不会随时间缩（day 3 snap 1.86GB，day 13 可能 6+GB）
- fork resume RAM peak 永远是 5-10× snapshot size

**可能根因**（待 audit）：

A. encounter events 都打了错的 day_index — 可能写入时全用当前 sim 时间的 day_index（也即当前 day），导致 evict 永远找不到比 "before_day_index" 小的：因为所有 events 都 day_index = recorder.current_day_at_record_time
B. kind 字段不是 `"encounter"` — ai-town port 后可能改名了 `physical_encounter` 之类，evict_cold_encounter_events 的 `if ev.kind == "encounter"` 严格匹配错过
C. schema 升级后 day_index 字段缺失或 None — evict 条件 `ev_day is not None and ev_day < before_day_index` 短路

**最快诊断**:
```python
# 在 evict_cold_encounter_events 加诊断 log
n_encounter = sum(1 for e in self._events if e.kind == "encounter")
n_with_day = sum(1 for e in self._events if e.kind == "encounter" and e.day_index is not None)
n_old_enough = sum(1 for e in self._events if e.kind == "encounter" and e.day_index is not None and e.day_index < before_day_index)
logger.info(f"evict diag: total={len(self._events)} encounter={n_encounter} with_day={n_with_day} old_enough={n_old_enough}")
```

跑一次 publishable smoke 看 log，立刻知道哪个 condition 失败。

**严重性**：
- 这个 bug 让 backlog 1.6 + 1.7 全部内存压力机制都"看上去 work 实际无效"
- publishable 跑 5 day+ RSS 必然爆 cap → graceful_stop 频繁 → 数据 chain 断裂概率高
- 不修这个，明天重跑也是同样问题

**Owner**：未指定。**下次 publishable 之前必须修**。

**关联**:
- [[backlog 1.6]] snapshot-resume-ram-peak — 一直说"已解决"实际是这个 bug 在掩盖
- [[fix-encounter-eviction-tick-semantic]] 2026-05-20 — 上次也是 evict 相关 bug，可能跟这次同源
- [[parallelize-day-end-llm-batches]] 2026-05-21 — 一个改 day_end LLM 一个改 evict，正交


## 1.21 fork 启动只复制 snapshot，没复制 day 0-N summaries (2026-05-21 实测发现)

**触发**：2026-05-21 fork day 4-13 run (`publishable_v6_day4to13_fork_seed43`)
启动时 `/tmp/swt-v5-fork-day4to13.sh` 只复制了 baseline-prefix 的 snapshot 文件
到 4 个 variant 子目录，**没复制 day 0-3 的 day_summary.json**。

→ worker 启动时 `load_day_summaries()` 读到 0 个 day summary（仅 snapshot 里有
state，没有 per-day aggregate）。内存中 `run_metrics.per_day_summaries` 从空开
始，只累积 worker 自己跑的 day 3 (resumed partial) + day 4-13。

→ Worker 完成时写的 `seed_43.json` / `aggregate.json` / `contest.json` 缺
day 0-2 数据，day 3 是 11-tick partial 不是 full 288-tick。

**Post-process 已 documented**：
`data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43/POSTPROCESS_NEEDED.md`

**根因**：本次 fork 用临时 bash 脚本 `/tmp/swt-v5-fork-day4to13.sh`，没考虑 
`load_day_summaries()` 的入口语义。

**修复方案（写进 backlog 1.7 baseline-prefix-share 正式实施）**：

`tools/spawn_fork_variants.py`（拟新建工具）应：
1. 复制 baseline-prefix 全部 `seed_<N>_day{0..K}.summary.json` 到每个 variant 子目录
2. 复制 baseline-prefix 的 `seed_<N>_day{0..K}.partial.json`（虽然 cleanup_partials
   后已经清空，向后兼容）
3. 复制最新 periodic snapshot
4. 写 `SUITE_ANCHOR.json` 标记 fork 来源 + day 范围
5. spawn 4 worker with `--resume` + `--from-snapshot`

→ worker 启动时 `load_day_summaries` 读到完整 day 0-K，per_day_summaries 内存
正确。

**Owner**：未指定。**下次 publishable 用 baseline-prefix-share pattern 前必修**。

**关联**：
- [[backlog 1.7]] baseline-prefix-share 设计 — 这是它的正式实施前提
- [[backlog 1.11]] --resume 不保留 run_metrics — 跟此问题同源
- [[harden-parallel-publishable-run]] 2026-05-21 proposal — 应 incorporate 此 task

