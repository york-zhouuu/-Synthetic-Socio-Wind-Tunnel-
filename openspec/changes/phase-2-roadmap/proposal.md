# Change: phase-2-roadmap

## Why
Phase 1 已落地：Atlas / Ledger / Engine / Perception / Cartography /
AgentRuntime / MapService。Thesis 已由 `thesis-focus` 收敛为**一主三机制**
（canonical 见 `docs/agent_system/00-thesis.md`）：

```
algorithmic-input  →  attention-main  →  spatial-output  →  social-downstream
```

七块 Phase 2 能力在 thesis chain 上的位置：

| 能力 | Chain-Position | 在链条中的角色 |
|---|---|---|
| `memory` | `infrastructure` | 为 attention/social 提供事件与反思存储 |
| `social-graph` | `social-downstream` | 闭环 thesis：关系 / 弱连接的演化 |
| `orchestrator` | `infrastructure` | 驱动链条的 tick 循环 |
| `model-budget` | `infrastructure` | 控制 LLM 成本，不引入新边界 |
| `policy-hack` | `algorithmic-input` | 注入 feed 扰动，触发主边界变化 |
| `conversation` | `social-downstream` | 把 encounter 转化为可测量的社交转化率 |
| `metrics` | `observability` | 跨层采集链条四层的测量信号 |

**实验层依赖（`research-design` 引入）**：所有实验实现（`policy-hack` /
`metrics` / `social-graph`）的 `## Why` SHALL 引用
`openspec/specs/experimental-design/spec.md` 的条款（Rival Hypothesis
structure / 14-day protocol / β rigor / Hybrid ethics / Mirror rule /
Diagnosis-Cure-Outcome-Interpretation report）作为前置锚点；执行基建见
`openspec/changes/multi-day-simulation/`。

完成"反向注意力干预打破附近性盲区"的 thesis 验证仍缺以下能力（见
`docs/agent_system/00-thesis.md` 与 `docs/agent_system/03-干预机制与实验指标.md`）：

1. **Memory System** — agent 三层记忆（事件流 / 摘要 / 反思），否则 agent 无法
   做基于过去经历的社交判断。
2. **Social Graph** — agent 间的关系边（熟悉度、信任、圈层），
   否则无法度量"弱关系建立"。
3. **Orchestrator** — 全局 tick 循环、时间推进、并发 agent 调度；当前各模块
   只有库函数，无统一驱动。
4. **ModelBudget** — 按"剧情重要性 / 社交距离 / 地点接近度 / 干预关联度"
   动态给每个 agent 分配 Haiku / Sonnet 调用额度，控制 LLM 成本。
5. **Policy Hack 干预系统** — 注入式"数字干预"（广告牌、推送、活动海报等）的
   统一接口，供实验对比组使用。
6. **对话与信息传播** — 广播式多方 LLM 对话、信息跳数追踪（距离注入源 N 跳）。
7. **实验指标框架** — 轨迹偏离、网络密度、弱关系数、叙事质量的采集与对比。

这些能力共同构成 Phase 2 的范围。本 proposal 只给出路线图与顶层契约；
每个能力在进入实现前 SHALL 由一个独立的 change proposal 细化。

**前置门禁（两条并列）**：Phase 2 每块 change 的 `## Why` 章节 SHALL
同时满足：

1. **Fitness-report 锚点**（`realign-to-social-thesis` 引入）：至少引用
   一条 `data/fitness-report.json` 中 `status in {fail, skip}` 且
   `mitigation_change` 指向本能力的 AuditResult。这保证每块 Phase 2
   能力都有"Phase 1 实测缺口"作为动机锚点，而不是孤立的"愿望清单"。

2. **Chain-Position 声明**（`thesis-focus` 引入）：显式声明
   `Chain-Position: <algorithmic-input | attention-main | spatial-output |
   social-downstream | infrastructure | observability>`，并说明在该位置
   上的角色（新增 / 增强 / 连接上下游，或为什么不在链条上）。**不允许
   任何 change 引入新的并列"边界"概念**。详见
   `docs/agent_system/00-thesis.md` 的 "Chain-Position 门禁" 章节。

## What Changes

- 新增 7 个能力规格（`memory`、`social-graph`、`orchestrator`、
  `model-budget`、`policy-hack`、`conversation`、`metrics`）的顶层 ADDED 需求，
  规定其职责边界与对现有模块的依赖。
- 以"stub"形式先冻结接口契约，留待后续 change 细化 Scenario。

## Non-goals

- **不**在本 change 中实现任何代码。
- **不**预先决定 memory / 社交图的具体存储格式（SQLite vs Postgres vs 内存）。
- **不**锁定 LLM provider；`agent.profile.base_model` 仍为字符串。
- **不**引入任何对现有 Phase 1 规格的 MODIFIED/REMOVED 需求——
  若后续发现需要，另开 change。

## Impact

- 现有模块：零破坏。Phase 1 的 Atlas / Ledger / Engine / Perception /
  Cartography / Agent / MapService 契约保持不变。
- 新增模块将通过"只读 + 明确写入点"的方式接入 Ledger，继续保持 CQRS 单源头。
- 预计 Phase 2 实现完成后，1000 agent × 100 tick 单日模拟在成本与性能上可行
  （模型预算控制在千级 LLM 调用）。
