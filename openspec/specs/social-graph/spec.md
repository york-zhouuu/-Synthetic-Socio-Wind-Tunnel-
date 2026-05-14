# social-graph — pairwise tie 累积层

## Purpose

`social-graph` capability accumulates pairwise ties from the encounter
stream, providing a persistent layer for thesis-direct social mechanism
(weak ties / Granovetter framework). 它消费 orchestrator 暴露的 encounter
candidate，把每对 agent 的 encounter 历史归约为一个 `Tie`（含
`encounter_count` / `strength` / `first_seen_*` / `last_seen_tick`），供
agent / memory / metrics 层查询"我跟谁熟"、"哪些是弱关系"、"今天形成了几条
新 tie"。

模块：`synthetic_socio_wind_tunnel/social_graph/`
## Requirements
### Requirement: Tie 数据模型

`synthetic_socio_wind_tunnel/social_graph/models.py` SHALL 定义 frozen dataclass `Tie`：

```
agent_a: str           # canonical 较小者（lexico）
agent_b: str           # canonical 较大者
encounter_count: int   # 累计 encounter 次数（≥ 1）
strength: float        # ∈ [0.0, 1.0)，由 encounter_count 算出
first_seen_tick: int   # 首次记录的 tick
last_seen_tick: int    # 最近一次 encounter 的 tick
first_seen_day: int    # 首次记录的 day_index
```

- `Tie` SHALL 是 frozen dataclass（或 Pydantic frozen model），不可变；状态变化通过 `Tie` 副本完成。
- 任何 `Tie` 实例 SHALL 满足 `agent_a < agent_b`（lexicographic 顺序），保证 pair 唯一性。
- `strength` SHALL 由公式 `encounter_count / (encounter_count + K)` 计算，K 由 `SocialGraphService` 持有的常量决定（V1 default K=10）；`Tie` 自身**不**重复计算 strength（构造时由 service 提供）。

#### Scenario: 构造 Tie 满足 pair canonical ordering

- **WHEN** 调用 `SocialGraphService` 用 `record_encounter("linda", "emma", tick=10)`（lexico 反序）
- **THEN** 内部存储的 `Tie` SHALL 满足 `agent_a == "emma"`、`agent_b == "linda"`

#### Scenario: Tie 不可变

- **WHEN** 持有一个 Tie 实例尝试 `tie.encounter_count += 1`
- **THEN** SHALL 抛出 `dataclasses.FrozenInstanceError`（或 Pydantic 等价错误）

### Requirement: SocialGraphService 累积 encounter

`synthetic_socio_wind_tunnel/social_graph/service.py` SHALL 定义 `SocialGraphService` 类，提供以下方法：

```
record_encounter(agent_a: str, agent_b: str, tick: int, day_index: int) -> Tie
get_tie(agent_a: str, agent_b: str) -> Tie | None
ties_for(agent_id: str) -> list[Tie]
familiar_with(agent_id: str, threshold: float = 0.1) -> set[str]
weak_ties(agent_id: str) -> list[Tie]    # strength ∈ [0.1, 0.5]
strong_ties(agent_id: str) -> list[Tie]  # strength > 0.5
all_ties() -> list[Tie]
```

- `record_encounter` SHALL：
  - 把 `(a, b)` normalize 到 canonical lex 顺序
  - 若 pair 不存在，新建 Tie 并设 `encounter_count=1`、`first_seen_tick=tick`、`first_seen_day=day_index`、`last_seen_tick=tick`、`strength=1/(1+K)`
  - 若 pair 已存在，构造新 Tie：`encounter_count++`、`last_seen_tick=tick`、`strength` 重算；first_seen_* 不变
  - **同一 tick 内同 pair 重复调用 record_encounter SHALL 幂等**（不重复累计 encounter_count）
- `get_tie` SHALL 接受任意输入顺序，内部 normalize 后查询。
- `ties_for(agent_id)` SHALL 返回所有 `agent_a == agent_id OR agent_b == agent_id` 的 Tie 列表。
- `familiar_with(agent_id, threshold)` SHALL 返回所有 `strength > threshold` 的 tie 中"另一方" agent_id 集合。
- `weak_ties` / `strong_ties` 阈值 SHALL 在 service 层定义为常量：weak ∈ [0.1, 0.5]、strong > 0.5。
- 服务 SHALL 提供 `K: int = 10` 构造参数（半饱和点）；K 不变，多次构造同 K 的服务行为一致。
- 服务 SHALL **不**持久化（in-memory only）；不写文件 / 不调外部系统。
- 服务 SHALL **不**自动从 memory store 回填历史 ties；只从启动后接收的 record_encounter 调用累积。

#### Scenario: 首次 record_encounter 创建 Tie

- **WHEN** `service.record_encounter("emma", "linda", tick=10, day_index=0)`
- **THEN** `service.get_tie("emma", "linda")` SHALL 返回 `Tie(agent_a="emma", agent_b="linda", encounter_count=1, strength=1/11, first_seen_tick=10, last_seen_tick=10, first_seen_day=0)`
- **AND** `service.get_tie("linda", "emma")` SHALL 返回**同一**实例（顺序不敏感）

#### Scenario: 重复 encounter 累计

- **WHEN** 同 pair 在 tick=10、20、30 各 record 一次
- **THEN** 最终 Tie 的 `encounter_count == 3`，`strength == 3/13 ≈ 0.231`，`first_seen_tick == 10`，`last_seen_tick == 30`

#### Scenario: 同 tick 同 pair 幂等

- **WHEN** 同一 tick=10 内 record_encounter("emma", "linda", 10, 0) 调用 3 次
- **THEN** Tie 的 `encounter_count` SHALL 只 +1（终值 1），不是 3

#### Scenario: 强度公式 K=10

- **WHEN** 累积 encounter_count 分别为 1, 5, 10, 30
- **THEN** strength SHALL 分别约 0.091, 0.333, 0.500, 0.750（误差 < 0.001）

#### Scenario: weak vs strong tie 分类

- **WHEN** emma 与 4 个邻居 encounter_count 分别为 0, 2, 10, 30
- **THEN** `service.familiar_with("emma", threshold=0.1)` SHALL 含 encounter_count ≥ 2 的 3 个邻居（strength > 0.1）
- **AND** `service.weak_ties("emma")` SHALL 含 encounter_count ∈ [2, 9] 的部分（strength ∈ [0.1, 0.5)）
- **AND** `service.strong_ties("emma")` SHALL 含 encounter_count ≥ 10 的部分（strength ≥ 0.5）

#### Scenario: 服务不回填历史

- **WHEN** memory store 中已有 100 条 encounter MemoryEvent，但 service 是从 tick=50 启动且未做任何 record
- **THEN** `service.all_ties()` SHALL 返回空列表

### Requirement: 顶层 API re-export

`synthetic_socio_wind_tunnel/social_graph/__init__.py` SHALL re-export `Tie` 与 `SocialGraphService`。
顶层 `synthetic_socio_wind_tunnel/__init__.py` SHALL 同步 re-export，使得 `from synthetic_socio_wind_tunnel import SocialGraphService, Tie` 可用。

#### Scenario: 顶层 import 可用

- **WHEN** 在新代码中执行 `from synthetic_socio_wind_tunnel import SocialGraphService, Tie`
- **THEN** SHALL 不抛 ImportError；`SocialGraphService()` SHALL 可正常构造

### Requirement: SocialGraphService SHALL distinguish physical vs noticed encounters

`SocialGraphService` MUST provide two distinct recording methods:

- `record_physical_encounter(agent_a, agent_b, tick, day_index=0) -> Tie`:
  records that two agents shared a location at this tick. MUST NOT increment
  tie.strength (geographic colocation alone does not build social bonds).
- `record_noticed_encounter(agent_a, agent_b, tick, day_index=0) -> Tie`:
  records that the two agents actually noticed each other through the
  attention-noticing gate. MUST increment tie.strength via the existing
  `_strength(encounter_count)` formula.

The legacy `record_encounter` MAY remain as an alias for
`record_noticed_encounter` (preserving prior tests that expected strength
to grow per call), but new caller code SHALL use the explicit variant.

#### Scenario: physical encounter does NOT grow tie strength
- **WHEN** `record_physical_encounter("a", "b", tick=1)` is called 5 times
  on distinct ticks
- **THEN** the returned Tie.strength SHALL be 0.0 (no noticed encounters yet)

#### Scenario: noticed encounter grows tie strength
- **WHEN** `record_noticed_encounter("a", "b", tick=t)` for `t = 1..10`
- **THEN** Tie.strength SHALL be `10 / (10 + K)` where K is the service's K
  parameter

#### Scenario: mixed physical + noticed
- **WHEN** 5 physical_encounters + 2 noticed_encounters on distinct ticks
- **THEN** Tie.encounter_count SHALL be 7 (physical contact count) but
  Tie.strength SHALL reflect only noticed (`2 / (2 + K)`)

### Requirement: SocialGraphService SHALL expose time-decayed tie strength

`SocialGraphService` MUST provide `effective_strength(tie, now_tick) -> float`
that applies a 30-day half-life exponential decay to a Tie's raw strength
based on `(now_tick - tie.last_seen_tick)`:

```
days_since = (now_tick - tie.last_seen_tick) / TICKS_PER_DAY
decay = exp(-ln(2) × days_since / 30)
effective = tie.strength × decay
```

Raw `tie.strength` SHALL be left immutable; decay applied at read time only
so existing callers using `tie.strength` directly continue to see growth-only
behaviour (backward compat). New audit code MAY opt-in to decayed strength
via `effective_strength` / `weak_ties_decayed` / `strong_ties_decayed`.

`SocialGraphService.weak_ties_decayed(agent_id, *, now_tick) -> list[Tie]`
SHALL return ties whose `effective_strength(now_tick)` is in
`[WEAK_TIE_THRESHOLD, STRONG_TIE_THRESHOLD)`.

`SocialGraphService.strong_ties_decayed(agent_id, *, now_tick) -> list[Tie]`
SHALL return ties whose `effective_strength(now_tick)` is `≥ STRONG_TIE_THRESHOLD`.

#### Scenario: never-decayed tie keeps raw strength
- **WHEN** `effective_strength(tie, tie.last_seen_tick)` is called (now == last_seen)
- **THEN** result SHALL equal `tie.strength` exactly

#### Scenario: 30-day-old tie at half strength
- **WHEN** a tie has `last_seen_tick = 0`, `strength = 0.5`, and now_tick =
  30 × 288 = 8640
- **THEN** `effective_strength(tie, 8640)` SHALL be ≈ 0.25 (50% decay)

#### Scenario: ancient tie effectively zero
- **WHEN** a tie has `last_seen_tick = 0`, `strength = 1.0`, and now_tick =
  365 × 288 (1 year)
- **THEN** `effective_strength(tie, ...)` SHALL be < 0.001

#### Scenario: weak_ties_decayed excludes faded ties
- **WHEN** a tie's raw strength is 0.15 (weak) but 60 days have passed
- **THEN** that tie SHALL NOT appear in `weak_ties_decayed(agent_id, now_tick=60*288)`
  (effective 0.15 × exp(-60/30) ≈ 0.020, below WEAK_TIE_THRESHOLD)

