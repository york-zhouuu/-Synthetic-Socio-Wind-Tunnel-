## Context

Publishable 单 worker run 当前 wall-clock 8–15 hour，机器 70% CPU IDLE，
其中真正瓶颈未经测量。backlog 1.14 提议的优化方向（spatial index for
encounter detection）经 grep `orchestrator/service.py::_detect_encounters`
被推翻——detection 是 location-bucket pair generation，O(L + Σ
visitors²)，非 Euclidean。所有 1.14 上层估算（5-10× speedup）建立在
错误假设上。

本 change 决定**先测量再优化**：交付 profile 工件 + baseline fixture +
regression guard，但**不改任何 production code**。下一个 change 拿到
真实 hot-path 数据后再针对性优化。

## Goals / Non-Goals

**Goals:**
- 量化 dev mode (100 agent × 1 day) 跑下来 top-30 函数 cumulative time
  占比
- 把测量结果 git-track 成 fixture，未来 PR 可机器 diff
- 给 regression guard：top-3 hot path 不应**未经讨论**地变化
- 写一份判读文档，让团队基于数据决定下一个优化方向

**Non-Goals:**
- 不写优化代码（任何 production 改动）
- 不揽 1.14 后续的优化决策——本 change 只提供决策**输入**
- 不引入 CI-level performance benchmark 流水线（更重的活）
- 不 profile 1000-agent publishable scale（dev mode 100 agent 足够定性，
  scale-up 在下一个 change）

## Decisions

### 决策 1：用 cProfile（stdlib）+ 可选 py-spy

**选项 A（采纳）**：cProfile (stdlib) 为主 — 数据 deterministic，可序列化，
易 diff。py-spy 作为可选附加产出火焰图（人看用，不入 fixture）。

**选项 B**：纯 py-spy。
**选项 C**：scalene / line-profiler。

选 A 因为：
- cProfile 输出可 stable serialize 进 fixture（py-spy SVG 不能 diff）
- stdlib，零依赖添加
- 与 pytest 集成方便（fixture 测试可调用 cProfile.Profile().runcall）
- py-spy 作为人类看的火焰图附加，但不在测试关键路径上

### 决策 2：dev mode 100 agent × 1 day 作为 profile scale

**选项 A（采纳）**：dev mode 100 × 1 day。
**选项 B**：publishable mode 1000 × 14 day。

选 A 因为：
- dev mode 跑完 < 60s，fixture 生成可在 CI / 单 dev 机器跑
- 100 agent 已足够 catch 100^2 = 10000 pair 量级 hot path（如真有）
- 1000 agent × 14 day 跑 8h 不现实，不能进 CI
- 量化分析显示比例 / 占比这些**相对**指标，scale 无关

**风险**：dev 100 agent 的 hot path 排序**可能**与 publishable 1000
agent 不同——例如 O(N²) 的算法在 N=100 还看不出，N=1000 才主导。
**Mitigation**：本 change 在 hot-path-analysis 文档明确标注"100-agent
profile 的 hot-path 排序可能在 1000-agent 下重排"，下一个 change 起
跑前如有疑问可选做 1000-agent profile（成本几 hour）。

### 决策 3：fixture 容量 top-30 而非 top-10 或全函数

**选项 A（采纳）**：top-30 函数（按 cumulative time 排序）入 fixture。

理由：
- top-10 太少，跨 Python 版本时排序可能 shuffle 看起来 regress
- 全函数（数千个）fixture 太大 + 噪音多
- top-30 通常覆盖 95%+ cumulative time，足够 catch 任何有意义的 shift

### 决策 4：regression test 只断言 top-3 函数集合 + wall-clock budget

**选项 A（采纳）**：断言 top-3 函数集合（**不是顺序**）+ dev smoke 总
wall-clock < N seconds。
**选项 B**：断言 top-30 完全等价。
**选项 C**：仅 wall-clock < N seconds。

选 A 因为：
- B 太严：Python GC / OS scheduling 抖动会让 top-30 第 25 名 vs 第 26
  名经常 swap，测试经常 false-fail
- C 太松：catch 不到"某函数大幅变慢但被另一个函数小幅变快抵消"的
  silent regression
- A 平衡：top-3 是**结构性** hot path，不太抖动；变化 = 真有改动

**Wall-clock budget** 设 dev smoke 当前测量值 × 1.5（50% 余量）作初值，
新 change 主动收紧。

### 决策 5：fixture 不进 git-LFS，直接 commit

**选项 A（采纳）**：fixture 是 JSON < 50KB，直接 git track。

理由：~50KB JSON 跟一个 short Python script 同量级；不需要 LFS 复杂度。

## Risks / Trade-offs

- **[Risk] Profile 本身改变运行时性能** → cProfile overhead ~10-30%。
  Mitigation：fixture 记 wall-clock 时明确标注"with cProfile attached"；
  下一个 change 测真实优化效果时**关掉** profile。

- **[Risk] dev 100 agent hot path ≠ publishable 1000 agent hot path** →
  见决策 2 Mitigation。

- **[Risk] py-spy 可选性导致 dev 之间 fixture 不可重复** → py-spy SVG
  不入 fixture，只 cProfile JSON 入；JSON 是 stdlib，所有 dev 都能生。

- **[Trade-off] 不优化任何代码，纯 measurement** → ROI 体感"没产出"；
  但**对**了：这一步的产出是**让下一步对**，比直接乱优化省的 wall-clock
  数量级更大。

## Migration Plan

1. 实施 `tools/profile_publishable_smoke.py` + 跑一次落 fixture
2. 写 regression test 跑通
3. 写 hot-path-analysis 文档
4. archive 本 change
5. 基于 fixture 数据，开第二个 openspec change 实施真实优化

**回滚**：纯新增文件，rollback = `git revert` 即可，零 production 风险。

## Open Questions

- 是否在 fixture 里也记录 memory peak (`tracemalloc`)？倾向：本 change
  scope 已经定为 measurement，先只记 cProfile；memory profile 留下一步
  （如果 RAM peak 是后续真问题）。
- 是否要在 CI 自动跑 profile？倾向：**不**，profile 在 dev 机器跑、
  fixture 进 git；CI 只跑 regression guard test 验证 fixture 没变形。
