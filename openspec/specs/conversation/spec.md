# conversation — 信息传播层

## Purpose

conversation capability layers information propagation onto encounter
events. Each push delivery becomes an Information origin; encounters
between agents probabilistically share known info, with hops tracked per
(agent, info) pair. V1 uses a probabilistic stub (no LLM dialogue);
LLM-driven multi-turn dialogue is V2 territory.

## Requirements

### Requirement: Information 数据模型

`synthetic_socio_wind_tunnel/conversation/models.py` SHALL 定义 frozen dataclass `Information`：

```
info_id: str
content: str
category: Literal["push", "observation", "rumor"]  # V1 只用 "push"
salience: float                          # ∈ [0.0, 1.0]
origin_tick: int
origin_agent_id: str
origin_day_index: int
source_feed_item_id: str | None = None   # 来自 push 时填
source_location_id: str | None = None    # 来自观察时填（V2）
```

- frozen / 不可变；信息内容 V1 不变形（无 Chinese whispers）。
- `salience` SHALL ∈ [0, 1]；构造时校验。
- `info_id` SHALL 全局唯一；service 负责生成。

#### Scenario: 构造合法 Information

- **WHEN** 用 `Information(info_id="i1", content="本街市集", category="push", salience=0.8, origin_tick=10, origin_agent_id="emma", origin_day_index=0)` 构造
- **THEN** SHALL 不抛；字段值与传入一致

#### Scenario: salience 越界 reject

- **WHEN** salience=1.5 或 -0.1
- **THEN** SHALL 抛 ValidationError 或 ValueError

#### Scenario: frozen 不可变

- **WHEN** 持有实例尝试 `info.content = "新内容"`
- **THEN** SHALL 抛 FrozenInstanceError

### Requirement: Propagation 聚合视图

`synthetic_socio_wind_tunnel/conversation/models.py` SHALL 定义 frozen dataclass `Propagation`：

```
info_id: str
reach: int                # 知道这条信息的 agent 数（含 origin）
max_hops: int             # 最长链路跳数
mean_hops: float          # 所有 known agent 的 hops 均值
known_at: dict[str, int]  # agent_id → first_learned_tick
hops_at: dict[str, int]   # agent_id → hops_at_learn
```

- 由 `ConversationService.get_propagation(info_id)` 工厂构造，不暴露给 caller 直接构造的语义。
- frozen / 不可变。

#### Scenario: 单 origin 的 Propagation

- **WHEN** 仅 origin agent 知道 info（无 share）
- **THEN** Propagation.reach SHALL == 1，max_hops == 0，mean_hops == 0.0

#### Scenario: 跳跃后聚合

- **WHEN** origin emma → linda(hops=1) → john(hops=2)
- **THEN** reach==3，max_hops==2，mean_hops==(0+1+2)/3=1.0

### Requirement: ConversationService 概率传播主入口

`synthetic_socio_wind_tunnel/conversation/service.py` SHALL 定义 `ConversationService` 类，提供：

```
record_origin(info: Information, agent_id: str, tick: int) -> None
process_tick(tick_result, social_graph, sim_day: int) -> list[ShareEvent]
get_propagation(info_id: str) -> Propagation | None
info_known_by(agent_id: str) -> set[str]    # info_ids
top_propagated(n: int = 10) -> list[Propagation]
all_infos() -> list[Information]
info_count() -> int
max_hops() -> int
count_reaching(min_hops: int) -> int
avg_reach() -> float
```

- `record_origin` SHALL 把 Info 加入 service 的 info catalog；agent_id 立刻 known，hops=0
- `process_tick` SHALL：
  - 遍历 `tick_result.encounter_candidates`
  - 对每对 (a, b)：取 a 与 b 各自 known 但对方未 known 的 info
  - 对每条这样的 info，按公式 `P = base × tie_mod × pers_mod × salience × recency_decay` 决定是否 share
  - share 时：let `hops_for_receiver = hops_of_sender + 1`；调 ledger.learn(receiver, info, tick, hops)
  - 返回本 tick 实际发生的 share 列表（dev / inspector 用）
- 概率公式各 modifier：
  - `base = 0.15`
  - `tie_mod = 0.5 + 1.0 × tie.strength`（tie 不存在时 strength=0 → 0.5）
  - `pers_mod = (extra_a + extra_b) / 2`（personality 由 caller 通过 agents map 传入）
  - `salience` 取自 info.salience
  - `recency_decay = exp(-days_since_origin / 3)`，days_since_origin = sim_day - info.origin_day_index
- 每个 (agent, info) pair 的 hops_at_learn SHALL 记录第一次 learned 时的 hops；后续路径不更新（最短路径语义）。
- 已 known 的 info SHALL 不重复 share；A→B→A 的反向链路自动跳过。
- service SHALL 接受 `seed: int | None` 构造参数，内部持有 seeded `random.Random` 用于概率门判定（reproducibility lock）。
- service SHALL **不**自动从 push delivery 中创建 Information——这是 caller（MemoryService）的职责。
- service SHALL 是 in-memory only；不持久化、不回填。

#### Scenario: record_origin 让 origin agent 立即 known

- **WHEN** `service.record_origin(info, "emma", tick=10)`
- **THEN** `service.info_known_by("emma")` SHALL 含 info.info_id
- **AND** `service.get_propagation(info.info_id).hops_at["emma"]` SHALL == 0

#### Scenario: 已知 info 不重复 share

- **WHEN** emma 知道 info；linda 不知道；调 process_tick 后 linda 也知道；下一 tick emma 跟 linda 又 encounter
- **THEN** 不会有 share 事件（双方都 known）；service 内部不重复处理

#### Scenario: 反向链路不更新 hops

- **WHEN** origin emma(hops=0) → linda(hops=1)（tick 10）→ john(hops=2)（tick 20）→ john 与 emma 在 tick 30 encounter
- **THEN** emma 的 hops_at_learn 不变（仍 0）；emma 已 known，不重复 share

#### Scenario: salience 影响 share 概率

- **WHEN** 跑 1000 次同 personality 同 tie 同 recency 的 share 决策；info_a salience=0.8，info_b salience=0.3
- **THEN** info_a 的实际 share 数 SHALL 显著高于 info_b（差距 > 30%）

#### Scenario: recency 衰减影响

- **WHEN** 同样 share 决策，info 的 origin_day_index 分别为今日（0 days ago）和 9 天前
- **THEN** 今日 info 的 share 数 SHALL 显著高于 9 天前的 info（recency_decay = e^(-0/3)=1 vs e^(-9/3)≈0.05）

#### Scenario: 同 seed reproducible

- **WHEN** 同 seed 同输入两次跑 process_tick
- **THEN** 两次的 share 决策序列 SHALL 完全一致

### Requirement: InformationLedger per-agent 索引

`synthetic_socio_wind_tunnel/conversation/service.py` SHALL 定义内部类 `InformationLedger` 或等价数据结构：

- `_known: dict[agent_id, dict[info_id, _Knowledge]]`，其中 `_Knowledge = (first_learned_tick: int, hops_at_learn: int)`
- `learn(agent_id, info_id, tick, hops)`：仅当 (agent_id, info_id) 不在 _known 中时插入；已存在则忽略（最短路径语义）
- `knows(agent_id, info_id) -> bool`
- `agents_who_know(info_id) -> set[str]`
- `hops_for(agent_id, info_id) -> int | None`
- internal data；不暴露 frozen API；ConversationService 是 façade

#### Scenario: learn 只记录第一次

- **WHEN** ledger.learn("emma", "i1", tick=10, hops=2)；后再 ledger.learn("emma", "i1", tick=20, hops=1)
- **THEN** ledger.hops_for("emma", "i1") SHALL == 2（保留第一次）

### Requirement: 顶层 API re-export

`synthetic_socio_wind_tunnel/conversation/__init__.py` SHALL re-export `Information`、`Propagation`、`ConversationService`。
顶层 `synthetic_socio_wind_tunnel/__init__.py` SHALL 同步 re-export。

#### Scenario: 顶层 import 可用

- **WHEN** `from synthetic_socio_wind_tunnel import ConversationService, Information, Propagation`
- **THEN** SHALL 不抛 ImportError
