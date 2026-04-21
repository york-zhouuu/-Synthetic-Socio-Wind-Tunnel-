# Smoke Experiment Demo — 首次全栈集成验证

**日期**：2026-04-21
**脚本**：`tools/smoke_experiment_demo.py`
**目的**：在真实 Lane Cove atlas 上跑通 orchestrator + attention + memory +
typed-personality，验证能否产出 Experiment 1 (Digital Lure) 的最小 thesis 信号。

## 结果

```
SMOKE EXPERIMENT REPORT  (seed=42, agents=100)
====================================================================
[A] plan generation                                     ✓
    plans_generated: 100
    total_plan_steps: 508
[B] movement                                            ✓
    move_success: 509 / failed: 0
    unique_locations_visited: 53
[C] encounter detection                                 ✓
    total_encounters: 3713
    ticks_with_encounters: 29 / 288
[D] memory events                                       ✓
    events_per_agent median: 363
    min/max: 302 / 425
[E] attention channel                                   ✓
    notif→target: 50 / 50
    notif→control: 0 / 50
[F] replan trigger                                      ✓
    replans_triggered: 100
    distinct agents: 50
[G] thesis signal                                       ✓
    target agents AT target_location: 50 / 50  (100%)
    control agents AT target_location:  7 / 50  ( 14% 自然基线)
    target median dist: 0.0m
    control median dist: 302.2m
    delta: +302.2m
[H] performance                                         ✓
    wall time: 1.2s
    per-tick avg: 4.0 ms
====================================================================

SUMMARY: 8 / 8 sub-goals PASS
```

## 要点解读

- **delta +302m** 是 target 和 control 的**行为差异**，不是"推送直接导致
  100% 到达"。真实 treatment effect = 100% − 14% = 86 pp。
- **14% 控制组自然基线** 来自：target_location 本身就在"20 常去地点 pool"
  里，一些 control agent 的 scripted plan 恰好随机选到它。这在真实实验里
  对应"所在街道本就是大家日常会去的"——需要减去。
- **1.2s 跑 100×288** 说明 Ledger 逐 step 写的成本可控。orchestrator +
  memory 的 Python 实现不是瓶颈。
- **连通度**：Lane Cove atlas outdoor_area 主连通分量 89.9% (4310/4794)，
  179 个小岛（top 5：4310 / 42 / 36 / 21 / 15）。building 主分量 93.8%。
  smoke demo 的 `_pick_connected_destinations` BFS 是避开小岛的必要步骤；
  否则随机选 20 个 destination 有 10% 概率落入孤岛，导致路由失败。
  已由 `tests/test_cartography.py::TestLaneCoveConnectivity` 门禁（≥85%）。

## 过程中发现的 2 个未来债务

这两个问题在 smoke demo 里被 StubLLM 的稳定输出掩盖了，但真实 LLM 下会
暴露。记入 phase-2-roadmap 作为后续 change 的锚点。

### 债务 #1：MemoryService 的 notification 去重基于 timestamp

`MemoryService._ingest_notifications` 用 `since = last_seen_timestamp` 过滤
新通知；但 `AttentionService.notifications_for(since=t)` 使用 `>=` 语义
（`if event.timestamp < since: continue`）。

**后果**：同一 notification 在 tick 96 被 ingest 一次后，tick 97-287 每次
`process_tick` 都会重新 ingest 相同的事件，每次都是新的 MemoryEvent
（tick 不同）→ 每 tick 都触发一次 should_replan → 每 tick 都调
`planner.replan`。

smoke demo 里不爆，因为 StubLLM 每次返回相同的 plan，重复 replan 等效于
no-op。真实 LLM 下会出现：
- 每 tick 1 次 LLM 调用 per 被推送的 agent = 成本爆炸
- plan 每 tick 被略微不同的 LLM 输出覆盖 → 行为不稳定

**修复方向**：用 `feed_item_id` 去重（per-agent `set[str]`），不是 timestamp。
归属 change：下次 memory 迭代，或独立为 `memory-consumption-tracking` change。

### 债务 #2：Planner.replan 的 step.time 不保证 > current_time

`StubReplanLLM` 初版硬编码 `time="8:15"`。下午 15:00 发生 replan 时，
`AgentRuntime._current_step_expired` 判定 step 已过期（8:15 < 15:00），
自动 advance 跳过，agent 不执行。smoke 初次跑得到 delta=-13.7m 就是这个。

**后果**：真实 LLM 可能返回早于 current_time 的 step time——尤其是 prompt
里若有"今天日程"这种词汇，LLM 倾向用清晨时间。Agent 会静默忽略 replan
指令。

**修复方向**：Planner.replan 在 parse 后做保底，若 `step.time < current_time`
则改写为 `current_time + tick_minutes`（或者 prompt 里强化"必须晚于当前"
并重试）。归属 change：下次 memory 迭代。

## 结论

**"拼装"层可用**——orchestrator + attention + memory + typed-personality
在真实规模数据上产出 thesis 信号，路径清晰可观测。

**两个待还的债务都在 memory 层面**，不影响开始下一块 Phase 2 能力（如
`social-graph` / `policy-hack`）的设计，但在 memory 的下一次迭代中应先还。

## 使用

```bash
python3 tools/smoke_experiment_demo.py --agents 100
python3 tools/smoke_experiment_demo.py --agents 50 --debug
python3 tools/smoke_experiment_demo.py --trace-agent a_42_0002 --debug
```

不是单元测试——不在 pytest 中跑，不做 CI 门禁。用作：
- 换底层 change 后的人工冒烟
- Experiment 1 设计前的 baseline 诊断
- 性能回归的基准对照
