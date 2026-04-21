# Tasks — phase-2-roadmap

> 本 change 为路线图；每项任务是一个**触发器**——真正开工前，
> 应为该项开独立 change proposal 并细化 Scenario。
>
> **前置门禁（由 `realign-to-social-thesis` 引入）**：每块能力的独立 proposal
> 的 `## Why` 章节 **SHALL** 至少引用一条 `data/fitness-report.json` 中
> `status in {fail, skip}` 且 `mitigation_change` 指向本能力的 AuditResult。
> 审计文件由 `make fitness-audit` 生成；能力名与 `mitigation_change` 字段
> 的对应关系写在 `docs/agent_system/07-审计报告解读.md`。

## 1. Memory
- [ ] 1.1 为 `memory` 写独立 proposal，定义三层记忆（事件流 / 日摘要 / 反思）的数据结构
- [ ] 1.1a 在 proposal `## Why` 中引用 `fitness-report.json` 中
      `mitigation_change == "memory"` 的 AuditResult（至少 `e3.shared-task-memory-seam`）
- [ ] 1.2 与 Ledger 的 `AgentKnowledgeMap` 协调：事件流写入点、反思读取点
- [ ] 1.3 规定记忆检索接口（供 Planner prompt 拼装使用）

## 2. Social Graph
- [ ] 2.1 为 `social-graph` 写独立 proposal，定义关系边与强度
- [ ] 2.1a 在 proposal `## Why` 中引用 `fitness-report.json` 中
      `mitigation_change == "social-graph"` 的 AuditResult（若现无 skip/fail 条目指向
      此能力，proposal 需自己说明 thesis 层面的动机 + 建议为后续 audit 添加该条目）
- [ ] 2.2 决定关系更新触发点（共处、对话、信息传播、拒绝互动等）
- [ ] 2.3 定义"弱关系"（Granovetter 式）的可计算指标

## 3. Orchestrator
- [ ] 3.1 为 `orchestrator` 写独立 proposal，定义 tick 结构与并发模型
- [ ] 3.1a 在 proposal `## Why` 中引用 `fitness-report.json` 中
      `mitigation_change == "orchestrator"` 的 AuditResult（尤其是 `scale.wall-time`
      若 fail，或 `cost.daily-upper-bound` 若 fail）
- [ ] 3.2 规定 agent 调度顺序、冲突解决（两 agent 同时拾取一物）
- [ ] 3.3 定义"路径相遇"检测位于 Orchestrator 还是 Simulation

## 4. Model Budget
- [ ] 4.1 为 `model-budget` 写独立 proposal，定义预算分层函数
- [ ] 4.1a 在 proposal `## Why` 中引用 `fitness-report.json` 中
      `mitigation_change == "model-budget"` 的 AuditResult（`cost.daily-upper-bound` 若 fail）
- [ ] 4.2 输入维度：主角身份、社交距离、地点接近度、干预关联度
- [ ] 4.3 输出：每 tick 每 agent 的 LLM 调用许可（Sonnet/Haiku/跳过）

## 5. Policy Hack（干预系统）
- [ ] 5.1 为 `policy-hack` 写独立 proposal，汇总 5 类干预
      （广告牌 / 推送 / 海报 / 活动事件 / 邻里消息）
- [ ] 5.1a 在 proposal `## Why` 中引用 `fitness-report.json` 中
      `mitigation_change == "policy-hack"` 的 AuditResult；与 `attention-channel`
      的边界需在 proposal 中明确（本 change 已建成 channel，policy-hack 负责触发）
- [ ] 5.2 定义干预注入的统一接口：在哪个位置、何时、内容、目标人群
- [ ] 5.3 规定干预可被 perception 捕获的通道（视觉/听觉/推送流）

## 6. 对话与信息传播
- [ ] 6.1 为 `conversation` 写独立 proposal，定义多方广播式对话
- [ ] 6.1a 在 proposal `## Why` 中引用 `fitness-report.json` 中
      `mitigation_change == "conversation"` 的 AuditResult
- [ ] 6.2 规定信息跳数（hops from injection source）追踪机制
- [ ] 6.3 Planner 如何将"被告知的新信息"转为 Replan 的 interrupts

## 7. 实验指标
- [ ] 7.1 为 `metrics` 写独立 proposal，列出四类指标：
      轨迹偏离、网络密度、弱关系数、叙事质量
- [ ] 7.1a 在 proposal `## Why` 中引用 `fitness-report.json` 中
      `mitigation_change == "metrics"` 的 AuditResult；注意 `ledger-observability`
      已在 Phase 1.5 审计中被验证，为 metrics 实现提供了起点
- [ ] 7.2 定义采集接口与落地格式（CSV / Parquet / sqlite 中择一）
- [ ] 7.3 定义实验对比组的 seed/参数冻结方式

## 横切任务
- [ ] X.1 为新增模块建立统一的"写入即事件"约定，维持 CQRS 单源头
- [ ] X.2 补齐 pytest 夹具以覆盖跨模块集成（orchestrator 驱动下的多 agent）
- [ ] X.3 更新 `README.md` 与 `docs/WIP-progress-report.md` 的进度标记
