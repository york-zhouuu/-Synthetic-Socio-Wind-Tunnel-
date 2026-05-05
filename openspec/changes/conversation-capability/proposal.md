## Why

social-graph 已经让 sim 知道"谁认识谁"——但**认识 ≠ 交流**。当前 100 个 agent 在 Lane Cove 跑 14 天，weak ties 累积起来了，**没有一条信息从 agent A 流向 agent B**。这是 thesis 链条的最后一环：

> 手机注意力 → 附近性盲区 → hyperlocal push → 物理共在（done）→ 弱关系（social-graph done）→ **信息流动 → 社区涌现**（缺）

具体表现，跑下次 publishable suite 还会看到的尴尬：
- emma 收到一条 hyperlocal push："本街周六有市集"
- emma 去了市集，跟 linda（弱关系）聊了一阵
- linda 跟 john（弱关系）周一在 cafe 见面
- john **永远不知道有市集**——信息只在 emma 一人脑里

**为什么这层重要**：

1. **hyperlocal push 的真实社会效应在第二跳**：单纯让一个 agent 行为偏离 +172m 不是 hyperlocal 的全部价值——价值是"被推送的人把信息带出去 → 没收到推送的人也被影响"。这就是 word of mouth / hyperlocal viral 的核心机制。
2. **弱关系的功能**（Granovetter 1973 的原文论证）：weak ties 比 strong ties **更**重要——因为 weak ties 跨越社交圈层，是新信息的桥梁。social-graph 已经把"桥"建好了，conversation 让"信息"能走过去。
3. **mirror（global_distraction）的对照**：A' 应该在 conversation 层显著弱于 A——不是因为 A' 没有 weak ties，而是因为 A' 的 push 内容跟在地无关，不会被 agent 当成"值得跟邻居说一嘴"的事。

**为什么 V1 不做 LLM dialogue**：

- 14 day × 1000 agent × ~50 encounters/day-pair × N turns LLM = 预算爆炸
- 真正想测的是**信息是否从 A 流到 B**，不是"他们具体说了什么"
- Stub 路径（基于概率的 share / 不 share）足以测出"hp 比 baseline 多产出 2-hop+ 信息流"——这是 thesis 第一次让 mirror 在社会层"赢"
- LLM dialogue 留 V2，等基线信号稳固再加

## What Changes

### 新 Capability：`conversation`

新建 `synthetic_socio_wind_tunnel/conversation/` 模块：

- **`Information` 数据模型**（frozen dataclass）：一条可流动的信息单元
  - `info_id` / `content` / `category`（"push" / "observation" / "rumor"）
  - `origin_tick` / `origin_agent_id` / `origin_day_index`
  - `source_feed_item_id`（如来自 push）/ `source_location_id`（如来自观察）
  - `salience: float ∈ [0, 1]`：信息的"值得说一嘴"程度，影响传播概率（hyperlocal 高，global 低）

- **`InformationLedger` per-agent 索引**：
  - `knows(agent_id) -> set[info_id]`
  - `learn(agent_id, info_id, tick, hops)`：记录 agent 知道了某 info（含 hops 数）
  - 每 (agent, info) pair 记录 `(first_learned_tick, hops_at_learn)`，hops_at_learn 是从 origin 到该 agent 的最短路径长

- **`ConversationService` 主入口**：
  - `record_origin(info, agent_id, tick)`：信息从 push / 观察直接进入 agent 的 known set，hops=0
  - `process_tick(tick_result, social_graph)`：扫描本 tick 的 encounter_candidates，按概率公式决定哪些 pair 共享信息；hops 累加
  - `get_propagation(info_id) -> Propagation(reach, max_hops, mean_hops)`：每条 info 的传播态查询
  - `top_propagated(n)` / `info_known_by(agent_id)` 等辅助查询

### 概率传播公式（V1 核心）

```python
P(share | encounter) = base × tie_modifier × personality_modifier × salience × recency_decay
```

具体：
- `base = 0.15`（基线 share 率；典型偶遇有 15% 概率谈到具体信息）
- `tie_modifier = 0.5 + 1.0 × tie.strength`（陌生人 0.5，强关系 1.5）
- `personality_modifier = avg(extraversion_a, extraversion_b)`（外向促进分享）
- `salience` ∈ [0, 1]（push 内容自带；hyperlocal=0.8 / global=0.3）
- `recency_decay = exp(-days_since_origin / 3)`（3 天半衰期；旧消息没人想说）

### 信息源（origin）注入

- **Push 路径**：`AttentionService.deliver` 后，attention-channel 拿到的 `FeedDeliveryRecord` SHALL 触发一次 `conversation.record_origin(info, agent_id, tick)`。salience 取自 FeedItem 的 hyperlocal_radius / category（hyperlocal_news → 0.8，commercial_push → 0.6，global_news → 0.3）。
- **直接观察**（V2）：感知到的事件可以变成 information——本 V1 不做。

### Modified：`memory` capability

- `MemoryService.__init__` 接受 `conversation: ConversationService | None`
- `process_tick` 在写完 encounter MemoryEvent + social_graph.record_encounter 之后，**额外调** `conversation.process_tick(tick_result, social_graph)` 让信息按概率传播

### Modified：`metrics` capability

`RunMetrics.info_propagation_hops` (现有 placeholder) 由工厂在 conversation 注入时填充：
```python
info_propagation_hops = {
    "info_count_total": int,        # 一共多少条 info origin
    "max_hop_observed": int,         # 任一 info 实际跳了几跳
    "info_reaching_2plus_hops": int, # 至少跳了 2 跳的 info 数（thesis 真正关心的）
    "avg_reach_per_info": float,     # 平均每条 info 到达多少 agent
}
```

`DayMetricsSummary` 加 4 个 daily counter（info_origins_today / info_shares_today / info_reaching_2plus_today / avg_hops_today）。

### Modified：`attention-channel` capability

`AttentionService.deliver` 或 `inject_feed_item` 之后 SHALL 通知 conversation（如果 conversation 注入到 AttentionService 或通过 hook 监听）。具体路径在 design.md 决定。最小侵入：让 MemoryService.process_tick 检查本 tick 新交付的 push，转换为 Information 调 record_origin。

### 非目标（Non-goals）

- ❌ **多轮 LLM dialogue**（V2）。本 V1 只有"share / 不 share"二态，不产 dialogue 文本
- ❌ **信息变形 / Chinese whispers**：信息内容不变，只跟踪传播
- ❌ **misinformation / rumor**：所有 info 一视同仁
- ❌ **trust 加权传播**：tie strength 替代了 trust（V1 简化）
- ❌ **topic modeling**：不分主题；info 是 opaque 字符串
- ❌ **回流抑制**：A→B→A 不会重复 share（已经 known 跳过），但不模拟"信息疲劳"
- ❌ **3+ agent 群聊**：本 V1 只有 pairwise share；多方对话留 V2

## Capabilities

### New Capabilities

- `conversation`：信息 / per-agent known set / 概率传播 / hops 追踪。基于 social-graph 的 tie strength 决定 share 概率。

### Modified Capabilities

- `memory`：`MemoryService` 接受 conversation；process_tick 在 social_graph 之后调 conversation.process_tick
- `metrics`：填 `info_propagation_hops` 字段（已有 placeholder）；DayMetricsSummary 加 4 个 daily counter
- `attention-channel`：保持 API 不变；MemoryService 负责把 push delivery 转成 Information origin（最小侵入）

### Untouched

- `social-graph` 不动（conversation 只读 tie strength）
- `agent` / `atlas` / `ledger` / `engine` / `perception`：不动
- `orchestrator` / `multi-day-run` / `policy-hack`：不动

## Impact

**代码新增**：
- `synthetic_socio_wind_tunnel/conversation/__init__.py`
- `synthetic_socio_wind_tunnel/conversation/models.py`（Information / Propagation）
- `synthetic_socio_wind_tunnel/conversation/service.py`（InformationLedger + ConversationService）
- 顶层 `__init__.py` re-export

**代码修改**：
- `synthetic_socio_wind_tunnel/memory/service.py`（接 conversation + process_tick 触发）
- `synthetic_socio_wind_tunnel/metrics/factory.py`（填 info_propagation_hops）
- `synthetic_socio_wind_tunnel/metrics/recorder.py`（per-day info counter）
- `synthetic_socio_wind_tunnel/metrics/models.py`（DayMetricsSummary 加 4 字段）
- `tools/run_variant_suite.py` / `tools/replan_trace.py` / `tools/export_inspector_payload.py`（构造 ConversationService 注入）

**测试新增**：
- `tests/test_conversation_models.py`（Information frozen / Propagation aggregation）
- `tests/test_conversation_service.py`（record_origin / probabilistic share / hops 累加 / known_by 查询 / salience + recency 衰减）
- `tests/test_conversation_integration.py`（mini sim：50 agent × 7 day baseline + hp，断言 hp 的 2-hop+ info 数 > baseline）

**Suite 影响**：
- 跑下一次 publishable suite 自动产出 `info_reaching_2plus_hops` 指标
- 预期 hp variant 显著高于 baseline——这是 thesis 中段第一次出现的"social signal"
- mirror（global_distraction）应**显著低于** hp（即使弱关系数量相当，因为 salience 低 → 信息留在原地）

**性能**：
- record_origin O(1)；process_tick 内对 encounter_candidates 遍历，每对调一次概率门 O(1)
- 1000 agent × 14 day × ~50 encounters/day-pair × ~10 known info per agent ≈ 10k decisions/day，ms 级

**Non-goals reaffirmed**：
- ❌ V1 不做 LLM dialogue。如果 publishable run 显示 V1 stub 的概率传播跟"真实人类对话"系统性偏离，再开 V2。
- ❌ V1 不做 information mutation；信息是 opaque 字符串。
