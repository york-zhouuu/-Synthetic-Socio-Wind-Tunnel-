# Design Notes — phase-2-roadmap

## 为什么是路线图而非单个大 change

Phase 2 涵盖 7 个独立能力，总规模 ≈ Phase 1 的 50–70%。若合并为单一 change：

- proposal 过长难评审；
- 任何一块推进都会阻塞其它；
- 实验假设可能在实现过程中推翻（例如"弱关系"的定义会随探索调整），
  导致频繁改动巨型 proposal。

因此本 change 只冻结"模块边界与命名"，细节每块各自 proposal。

## 模块边界（宏观草图）

```
┌────────────────────────────────────────────────────────────────┐
│                       Orchestrator                             │
│  tick loop · agent 调度 · 路径相遇检测 · 冲突裁决                │
└────────────────────────────────────────────────────────────────┘
         │                │              │               │
         ▼                ▼              ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│   Agent      │ │ Conversation │ │   Memory     │ │ Social Graph │
│  (Phase 1)   │ │  多方广播LLM  │ │ 事件/摘要/反思 │ │ 关系/信任     │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
         │                │              │               │
         ▼                ▼              ▼               ▼
┌────────────────────────────────────────────────────────────────┐
│  Model Budget   │    Policy Hack     │     Metrics             │
│  （LLM 额度）     │  （注入式干预）      │  （实验指标采集）          │
└────────────────────────────────────────────────────────────────┘
                            │
                            ▼
         ┌───────────────────────────────┐
         │  Phase 1: Atlas / Ledger /    │
         │  Engine / Perception /        │
         │  Cartography / MapService     │
         └───────────────────────────────┘
```

读/写约定：
- **Orchestrator**：唯一驱动者，写入点为"推进 tick"。
- **Memory / Social Graph / Metrics**：读 Ledger + 事件流；写自身专属存储。
- **Policy Hack**：写入 Ledger（增添广告牌 entity / 临时 affordance），
  保证仍只由 CQRS 的命令侧经过一次。
- **Model Budget**：纯函数式决策层，无持久状态。

## 依赖 Phase 1 的锚点

- `core.events.WorldEvent` 是跨模块广播的消息单位；Memory / SocialGraph /
  Metrics 都订阅 WorldEvent 流。
- `AgentKnowledgeMap` 由 MapService 主导更新；Memory 在其上添加时间线。
- `SimulationErrorCode` 提供的结构化错误在 Orchestrator 中决定是否触发 Replan。

## 关键未决

- **存储选型**：短期仍放内存 + JSON dump；1000 agent 日志累计约 1–10MB，
  可接受。若进入多日长程仿真，再升级到 SQLite。
- **LLM provider**：默认 Anthropic（Opus/Sonnet/Haiku）；`base_model` 字段保持
  字符串以便日后扩展到其它 provider。
- **实验对比协议**：必需冻结随机种子 + profile 生成种子 + Policy Hack 注入种子，
  确保 A/B 组仅干预变量不同。

## 参考文档

- `docs/项目Brief.md`
- `docs/agent_system/01-总体架构.md`
- `docs/agent_system/03-干预机制与实验指标.md`
- `docs/agent_system/05-补充-路径相遇与广播社交.md`
- `docs/WIP-progress-report.md`
