## MODIFIED Requirements

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
target_audience_tags: tuple[str, ...] = ()  # 新增（push-content-individualization）
```

- frozen / 不可变；信息内容 V1 不变形（无 Chinese whispers）。
- `salience` SHALL ∈ [0, 1]；构造时校验。
- `info_id` SHALL 全局唯一；service 负责生成。
- `target_audience_tags` 来自 origin push 的 FeedItem.target_audience_tags
  透传；用于 conversation metric 计 target_precision。**默认 ()** 时仍向后
  兼容（无 push-content-individualization 也能工作）。

#### Scenario: 构造合法 Information（向后兼容默认）

- **WHEN** 用 `Information(info_id="i1", content="本街市集", category="push",
  salience=0.8, origin_tick=10, origin_agent_id="emma", origin_day_index=0)`
  不传 target_audience_tags
- **THEN** SHALL 不抛；target_audience_tags SHALL == ()

#### Scenario: 构造含 target_audience_tags

- **WHEN** 传入 `target_audience_tags=("parents", "newcomer")`
- **THEN** 字段值与传入一致

#### Scenario: salience 越界 reject

- **WHEN** salience=1.5 或 -0.1
- **THEN** SHALL 抛 ValidationError 或 ValueError

#### Scenario: frozen 不可变

- **WHEN** 持有实例尝试 `info.content = "新内容"`
- **THEN** SHALL 抛 FrozenInstanceError

### Requirement: ConversationService 概率传播主入口

`synthetic_socio_wind_tunnel/conversation/service.py` SHALL 定义 `ConversationService` 类：

构造参数：
- `seed: int | None = None`：reproducibility lock 共享 seed
- `relevance_provider: Callable[[str, str], float] | None = None`（**新增**，
  push-content-individualization）：(info_id, agent_id) → relevance ∈ [0, 1]。
  None 时所有 relevance 默认 1.0（向后兼容）。

提供：

```
record_origin(info: Information, agent_id: str, tick: int) -> None
process_tick(tick_result, social_graph, sim_day: int,
             agents: Mapping[str, AgentRuntime]) -> list[ShareEvent]
get_propagation(info_id: str) -> Propagation | None
info_known_by(agent_id: str) -> set[str]
top_propagated(n: int = 10) -> list[Propagation]
all_infos() -> list[Information]
info_count() -> int
max_hops() -> int
count_reaching(min_hops: int) -> int
avg_reach() -> float
within_target_count(info_id: str) -> int        # 新增：触达 agents 中
                                                 # audience_tag ∈ target 的数
outside_target_count(info_id: str) -> int       # 新增
target_precision_for(info_id: str) -> float     # 新增：within / total
mean_target_precision() -> float                # 新增：跨所有 info 平均
```

- share 概率公式（V1 + push-content-individualization）：
  ```
  P = base × tie_mod × pers_mod × salience × recency_decay
      × sender_relevance × receiver_relevance
  ```
  - `base = 0.15`
  - `tie_mod = 0.5 + 1.0 × tie.strength`
  - `pers_mod = avg(extraversion_a, extraversion_b)`
  - `salience` 取自 info.salience
  - `recency_decay = exp(-days_since_origin / 3)`
  - `sender_relevance = relevance_provider(info_id, sender) if provider else 1.0`
  - `receiver_relevance = relevance_provider(info_id, receiver) if provider else 1.0`
  - 任一 relevance 不在 [0, 1]，应 clamp 到 [0, 1]

- `within_target_count(info_id)` SHALL 计算：触达该 info 的 agents 中，由
  caller 提供的 audience_tag 函数判定 tag ∈ info.target_audience_tags 的数量。
  audience_tag 判定通过 service 构造时另一可选参数 `audience_tag_provider:
  Callable[[str], str] | None = None`（接受 agent_id 返回 tag）。未注入时
  within_target_count 返回 0；mean_target_precision() 返回 0.0。

#### Scenario: 未注入 relevance_provider 时退化

- **WHEN** ConversationService 构造时 relevance_provider=None；
  跑 process_tick
- **THEN** share 概率公式 SHALL 行为等同 conversation-capability 之前
  （sender × receiver = 1.0 × 1.0 = 1.0 不影响）

#### Scenario: 注入 relevance_provider 后影响 share 概率

- **WHEN** relevance_provider 对 info_x 给 (emma, 1.0) 和 (john, 0.3)；
  跑 1000 次 emma → john 的 share 决策（其它一切相同）
- **THEN** 实际 share 比例 SHALL 显著低于 provider=None 的 baseline
  （0.3 receiver_relevance 让 P 缩到 30%）

#### Scenario: target_precision 在未注入 audience_tag_provider 时为 0

- **WHEN** service 构造时 audience_tag_provider=None
- **THEN** mean_target_precision() SHALL 返回 0.0；within_target_count
  SHALL 返回 0

#### Scenario: target_precision 计算正确

- **WHEN** info.target_audience_tags=("parents",)；3 个 agent 知道这条 info：
  agent_a tag="parents", agent_b tag="parents", agent_c tag="elderly"；
  audience_tag_provider 返回正确 tag
- **THEN** within_target_count(info_id) SHALL == 2
- **AND** target_precision_for(info_id) SHALL == 2/3 ≈ 0.667

### Requirement: ConversationService 概率传播 — process_tick

`process_tick` 在 push-content-individualization 引入后 SHALL 在原概率公式
基础上加入 sender / receiver relevance modifier：

- SHALL 遍历 `tick_result.encounter_candidates`
- 对每对 (a, b)：SHALL 取 a 与 b 各自 known 但对方未 known 的 info 集合
- 对每条这样的 info，SHALL 按扩展公式（含 sender_relevance + receiver_relevance）决定是否 share
- share 时：`hops_for_receiver = hops_of_sender + 1`；SHALL 调 ledger.learn(receiver, info, tick, hops)
- 已 known 的 info MUST NOT 重复 share；A→B→A 反向链路 SHALL 自动跳过
- 同 seed 输入下结果 SHALL reproducible

#### Scenario: relevance 公式对 baseline 的退化

- **WHEN** relevance_provider=None；跑同 seed 同输入
- **THEN** 结果 SHALL 与 conversation-capability 之前完全一致

#### Scenario: 跨 audience 边界传播显著弱化

- **WHEN** info.target_audience_tags=("parents",); audience_tag_provider 让
  emma=parents, mary=elderly; relevance_provider 让 emma 对该 info 1.0,
  mary 0.3; emma 与 mary 在 1000 次相同条件下 encounter
- **THEN** mary 最终 known 比例 SHALL 显著低于 emma=parents, linda=parents
  双 1.0 的对照（差距 > 30%）
