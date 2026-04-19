# Change: phase-2-roadmap

## Why
Phase 1 已落地：Atlas / Ledger / Engine / Perception / Cartography /
AgentRuntime / MapService。但完成"超在地性边界渗透"实验仍缺以下能力
（见 `docs/项目Brief.md` 与 `docs/agent_system/03-干预机制与实验指标.md`）：

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
