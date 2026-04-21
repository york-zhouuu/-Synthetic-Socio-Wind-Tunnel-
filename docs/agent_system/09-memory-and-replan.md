# Memory 与 Replan

本文件记录 `memory` change（归档于 2026-04-21）。

## 三件事

```
┌────────────────────────────────────────────────────────────────┐
│  1. 存                                                          │
│     MemoryEvent（kind / actor_id / location / urgency /          │
│                 importance / tags / embedding）                  │
│     MemoryStore per-agent + 4 路倒排索引                         │
│                                                                 │
│  2. 查                                                          │
│     MemoryRetriever 4-way 打分                                   │
│       - structural (query 字段命中)                              │
│       - keyword (substring)                                     │
│       - recency (指数衰减)                                       │
│       - embedding (cosine)                                      │
│     默认权重 {struct:0.4, keyword:0.15, recency:0.35, embed:0.10}│
│                                                                 │
│  3. Replan                                                      │
│     agent.should_replan(memory, candidate) -> bool              │
│       纯代码规则（读 profile.personality）                        │
│     planner.replan(profile, current_plan, ctx) -> DailyPlan     │
│       1 LLM 调用                                                 │
└────────────────────────────────────────────────────────────────┘
```

## 数据流

```
orchestrator.on_tick_end(tick_result)
    ↓
memory_service.process_tick(tick_result, agents, planner)
    ↓
┌────────────────────────────────────────────────────┐
│  Step 1: 从 tick_result.commits 派生 action events │
│          从 encounter_candidates 派生 encounter 双向 │
│          从 AttentionService 派生 notification /     │
│          task_received                              │
└──────────────────┬─────────────────────────────────┘
                   ↓
┌────────────────────────────────────────────────────┐
│  Step 2: 对每 agent：                                │
│          recent = memory.recent(agent, last_ticks=1)│
│          for candidate in recent:                  │
│            if agent.should_replan(recent, cand):   │
│              new_plan = planner.replan(...)        │
│              agent.plan = new_plan                 │
│              break  # 最多 1 replan/tick            │
└────────────────────────────────────────────────────┘
```

## should_replan 默认规则

```python
def should_replan(memory, candidate):
    adherence = profile.personality.routine_adherence  # typed!
    curiosity = profile.personality.curiosity

    if candidate.kind in ("notification", "task_received"):
        threshold = 0.4 + 0.3*adherence - 0.3*curiosity
        return candidate.urgency > threshold
    return False
```

- 高好奇 + 低坚持 → 低 urgency 也触发
- 高坚持 → 只有极高 urgency 才触发
- encounter / action / speech 默认不触发（各自由未来 change 扩展）

## 成本约束

```
每 agent 每 tick：
  memory.record 写入         零 LLM
  agent.should_replan        零 LLM
  planner.replan             0 或 1 次（触发式）

每 agent 每日：
  memory.run_daily_summary   1 次 LLM

1000 agents × 288 tick 单日：
  daily summary    ≈ 1000 calls
  replan           ≈ 0–50 calls (实测从 urgency 分布决定)
  ────────────────────────────
  合计             ≈ 1000–1050 LLM calls/day
```

## 集成示例

```python
from synthetic_socio_wind_tunnel.memory import MemoryService
from synthetic_socio_wind_tunnel.orchestrator import Orchestrator

orch = Orchestrator(atlas, ledger, agents, attention_service=attention)
memory = MemoryService(attention_service=attention)

agents_by_id = {a.profile.agent_id: a for a in agents}
orch.register_on_tick_end(
    lambda tr: memory.process_tick(tr, agents_by_id, planner)
)

summary = orch.run()

# End of day: LLM summary
daily_summaries = await memory.run_daily_summary(agents_by_id, llm_client)
```

## MemoryEvent 字段哲学

```
display 层            behavior 层               metadata
────────────────────  ────────────────────────  ────────────
content: str          urgency: float            event_id / tick
                      importance: float         simulated_time
tags: tuple[str,...]  participants: tuple       actor_id / location_id
  （仅描述性标签）         embedding: vec?
                      kind: Literal[...]
```

**不把数字藏在 tags 里**——typed-personality 之后沿用的原则。

## 未来扩展点

| 未来 change | 在 memory 上加什么 |
|---|---|
| `social-graph` | 订阅 encounter events → 聚合关系强度 |
| `conversation` | 产 speech events → memory 消费它们供下次对话 prompt |
| `policy-hack` | 注入 task_received，memory 记录触发链路 |
| `metrics` | 全量消费 MemoryEvent + DailySummary，出叙事质量指标 |
