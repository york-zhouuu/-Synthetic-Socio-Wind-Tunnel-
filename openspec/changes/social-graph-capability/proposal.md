## Why

100 个 agent 在 Lane Cove 跑 14 天，**两两之间永远是陌生人**——这是当前 sim 最大的 thesis 漏洞。

现状：
- `tick_result.encounter_candidates` 只承载"本 tick 同位置 co-location"瞬时事实，不累积。
- `MemoryService.events_at_tick` 写入 per-agent 的 `kind="encounter"` MemoryEvent，但**只是个体经历的流水**——agent A 知道"我今天看到了 B"，但 sim 系统不知道"A 跟 B 之间累积了什么"。
- `Planner._build_replan_prompt` 的 `【周围】` block 用 `is_familiar` 标记，目前只能在 memory 里搜 actor_id 是否曾出现过——**有出现过 ≠ 存在弱关系**（一次擦肩 vs 14 天天天碰面是两回事）。

这个 gap 让 thesis 中段直接断了：

> **Thesis 全句**：手机注意力造成"附近性盲区" → hyperlocal push 把人拉回物理附近 → ……（断在这）……→ 邻里弱关系建立 → 社会结构涌现

我们做了左半（attention → 物理偏离），缺右半（co-location → 弱关系）。哪怕 hyperlocal push 跑得再漂亮，**只有"trajectory deviation +172m"是个体层面的指标**——thesis 说的"社会结构修复"在我们的 sim 里**根本没有发生的位置**。

具体表现，即将看到的尴尬场景（v3 publishable 已经能复现）：
- baseline：100 个邻居在 Lane Cove 来回走 14 天，互相零认识
- hp：100 个邻居被推送拉去同一咖啡馆 5 次，互相**仍然零认识**
- 最终 metric 区别只能体现在"trajectory deviation"，社会层 0 信号

**为什么现在做**：
- attention-rebalance 已经把 push 的"个体行为偏离"拨到合理量级（v3 -14% encs，hp.traj_dev < gd.traj_dev 三次一致）
- 接下来真正要拷问的是"那这些 encounter 里有没有产生**关系**"——这是 thesis 真正的社会层产出
- push-content-individualization（下一个 change）的 ground truth 也依赖这层：只有先有 weak ties 概念，才能问"个体化 push 是否激活了 sleeping ties"

## What Changes

### 新 Capability：`social-graph`

新建 `synthetic_socio_wind_tunnel/social_graph/` 模块：
- `Tie` 数据模型（frozen dataclass）：`(agent_a, agent_b, strength, encounter_count, first_seen_tick, last_seen_tick)`，pair canonical ordering（lexico smaller 在前，dedup 干净）
- `SocialGraphService` 服务：
  - `record_encounter(a, b, tick, day_index)` 累积；同 tick 同 pair 幂等
  - `get_tie(a, b) -> Tie | None`
  - `ties_for(agent_id) -> list[Tie]`
  - `familiar_with(agent_id, threshold=0.1) -> set[str]`（用于 prompt 装配）
  - `weak_ties(agent_id) -> list[Tie]`（strength ∈ [0.1, 0.5]）
  - `strong_ties(agent_id) -> list[Tie]`（strength > 0.5）

**Strength 公式**（V1）：
```
strength = encounter_count / (encounter_count + K)    # K = 10
```
- 1 次 → 0.09
- 5 次 → 0.33
- 10 次 → 0.50（弱关系阈值）
- 30 次 → 0.75（强关系阈值不到，但已显著）

不引入时间衰减——V1 累积到位先看趋势；衰减留待 V2。

### Modified：`memory` capability

- `MemoryService.__init__` 接受 `social_graph: SocialGraphService | None`
- `process_tick` 在派生 encounter MemoryEvent 之外，**额外调** `social_graph.record_encounter(enc.agent_a, enc.agent_b, tick, day_index)` 一次 per encounter pair
- `nearby_agents` 装配（attention-rebalance 添加的）的 `is_familiar` 改用 `social_graph.familiar_with(agent_id)` 查询（取代当前的"memory 里有 actor_id"近似）

### Modified：`metrics` capability

`TickMetricsRecorder` 增加 social-graph 指标：
- `tie_count_total`（per-run 总弱+强关系数）
- `tie_count_weak`（strength ∈ [0.1, 0.5]）
- `tie_count_strong`（strength > 0.5）
- `new_ties_per_day`（首次出现于该日的 pair 数）
- `avg_ties_per_agent`

ContestReport / contest.json 自动消费新指标作为可选 primary_metric（hp variant 应明显高于 baseline）。

### Modified：`agent` capability

`AgentRuntime.familiar_with(other_id) -> bool`：调 social_graph 查 tie strength。`Planner._build_replan_prompt` 的 `【周围】` block 区分 `familiar` / `stranger` 时用此。

## Capabilities

### New Capabilities

- `social-graph`：跨 agent pairwise 关系累积层。基于 Granovetter 弱关系框架，把 encounter 流转化为 tie。

### Modified Capabilities

- `memory`：`MemoryService.process_tick` 额外调 `social_graph.record_encounter`；`nearby_agents` 装配 is_familiar 改查 social_graph。
- `metrics`：`TickMetricsRecorder` 加 4 个 tie 指标；ContestReport schema 加可选 primary_metric。
- `agent`：`AgentRuntime` 加 `familiar_with` 便捷方法（薄封装 social_graph）。

### Untouched

- `atlas` / `cartography` / `ledger` / `engine` / `perception`：不动
- `attention-channel` / `policy-hack` / `multi-day-run` / `orchestrator`：不动
- `attention-rebalance` 已 ship 的 prompt 结构 / should_replan：不动（只升级 is_familiar 来源）

## Impact

**代码新增**：
- `synthetic_socio_wind_tunnel/social_graph/__init__.py`
- `synthetic_socio_wind_tunnel/social_graph/models.py`（Tie）
- `synthetic_socio_wind_tunnel/social_graph/service.py`（SocialGraphService）
- 顶层 `__init__.py` re-export

**代码修改**：
- `synthetic_socio_wind_tunnel/memory/service.py`（接 social_graph + 在 process_tick 写入）
- `synthetic_socio_wind_tunnel/metrics/recorder.py`（4 个新指标）
- `synthetic_socio_wind_tunnel/agent/runtime.py`（`familiar_with` 便捷方法）
- `tools/run_variant_suite.py` / `tools/export_inspector_payload.py`（构造 SocialGraphService 注入 MemoryService）

**测试新增**：
- `tests/test_social_graph_models.py`（Tie 不可变 / pair canonical ordering）
- `tests/test_social_graph_service.py`（record_encounter idempotent within tick / strength formula / threshold queries）
- `tests/test_social_graph_integration.py`（mini sim：跑 50 agent × 7 day，断言 weak ties 出现 + hp variant 比 baseline 多）

**Suite 影响**：
- 跑下一次 publishable suite 会自动产出 `tie_count_*` 指标，可作为 thesis-direct evidence（hp.weak_ties > baseline.weak_ties）
- v3 publishable 数据**不会被新机制改写**（社交层是新增能力，不影响 encounter / traj_dev）

**性能**：
- record_encounter O(1)，每 tick 调用次数 = encounter_candidates 长度（典型 < 50）
- service 内部用 dict 索引，1000 agent × 100 ties/agent ≈ 50k tie pairs，内存 < 5MB

**Non-goals（明确不做）**：
- ❌ 时间衰减 / tie decay（V2）
- ❌ 信任 / 同质性偏置（trust / homophily）
- ❌ 多方对话 / 信息跳数（下一个 change：`conversation-capability`）
- ❌ Online vs offline tie distinction（数字层社交不在本 change 范围）
- ❌ 历史回填（启动新 service 时不从过去 memory 中重建 ties；从启动 tick 0 开始累积）
