# Tasks — phase-2-roadmap

> 本 change 为路线图；每项任务是一个**触发器**——真正开工前，
> 应为该项开独立 change proposal 并细化 Scenario。

## 1. Memory
- [ ] 1.1 为 `memory` 写独立 proposal，定义三层记忆（事件流 / 日摘要 / 反思）的数据结构
- [ ] 1.2 与 Ledger 的 `AgentKnowledgeMap` 协调：事件流写入点、反思读取点
- [ ] 1.3 规定记忆检索接口（供 Planner prompt 拼装使用）

## 2. Social Graph
- [ ] 2.1 为 `social-graph` 写独立 proposal，定义关系边与强度
- [ ] 2.2 决定关系更新触发点（共处、对话、信息传播、拒绝互动等）
- [ ] 2.3 定义"弱关系"（Granovetter 式）的可计算指标

## 3. Orchestrator
- [ ] 3.1 为 `orchestrator` 写独立 proposal，定义 tick 结构与并发模型
- [ ] 3.2 规定 agent 调度顺序、冲突解决（两 agent 同时拾取一物）
- [ ] 3.3 定义"路径相遇"检测位于 Orchestrator 还是 Simulation

## 4. Model Budget
- [ ] 4.1 为 `model-budget` 写独立 proposal，定义预算分层函数
- [ ] 4.2 输入维度：主角身份、社交距离、地点接近度、干预关联度
- [ ] 4.3 输出：每 tick 每 agent 的 LLM 调用许可（Sonnet/Haiku/跳过）

## 5. Policy Hack（干预系统）
- [ ] 5.1 为 `policy-hack` 写独立 proposal，汇总 5 类干预
      （广告牌 / 推送 / 海报 / 活动事件 / 邻里消息）
- [ ] 5.2 定义干预注入的统一接口：在哪个位置、何时、内容、目标人群
- [ ] 5.3 规定干预可被 perception 捕获的通道（视觉/听觉/推送流）

## 6. 对话与信息传播
- [ ] 6.1 为 `conversation` 写独立 proposal，定义多方广播式对话
- [ ] 6.2 规定信息跳数（hops from injection source）追踪机制
- [ ] 6.3 Planner 如何将"被告知的新信息"转为 Replan 的 interrupts

## 7. 实验指标
- [ ] 7.1 为 `metrics` 写独立 proposal，列出四类指标：
      轨迹偏离、网络密度、弱关系数、叙事质量
- [ ] 7.2 定义采集接口与落地格式（CSV / Parquet / sqlite 中择一）
- [ ] 7.3 定义实验对比组的 seed/参数冻结方式

## 横切任务
- [ ] X.1 为新增模块建立统一的"写入即事件"约定，维持 CQRS 单源头
- [ ] X.2 补齐 pytest 夹具以覆盖跨模块集成（orchestrator 驱动下的多 agent）
- [ ] X.3 更新 `README.md` 与 `docs/WIP-progress-report.md` 的进度标记
