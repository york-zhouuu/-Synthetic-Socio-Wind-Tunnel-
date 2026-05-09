## ADDED Requirements

### Requirement: Dialogue 数据模型

`synthetic_socio_wind_tunnel/conversation/dialogue.py` SHALL 定义：

```
DialogueStatus = Literal["invited", "walking_over", "participating", "ended"]

@dataclass(frozen=True)
class DialogueMessage:
    message_id: str
    speaker_id: str
    content: str
    tick: int

@dataclass
class Dialogue:
    dialogue_id: str
    initiator_id: str
    invitee_id: str
    status: DialogueStatus
    messages: list[DialogueMessage]      # mutable，service 内部 append
    started_tick: int
    last_message_tick: int
    target_location_id: str | None       # 双方走向哪
    ended_tick: int | None
    end_reason: str | None               # "leave" / "max_messages" / "timeout"
```

约束：
- `participants = (initiator_id, invitee_id)` 总是恰好 2 个 agent_id（V1 不支持 3+ 群聊）
- `messages` 单调递增（按 tick）
- `status` 只能按 invited → walking_over → participating → ended 顺序前进
  （participating → invited 等回退非法）

#### Scenario: 构造合法 Dialogue

- **WHEN** `Dialogue(dialogue_id="d1", initiator_id="emma", invitee_id="linda",
  status="invited", messages=[], started_tick=10, last_message_tick=10,
  target_location_id="cafe", ended_tick=None, end_reason=None)`
- **THEN** 构造成功；participants 自动派生为 ("emma", "linda")

#### Scenario: 同 agent 自指拒绝

- **WHEN** initiator_id == invitee_id
- **THEN** SHALL 抛 ValueError

### Requirement: DialogueService 状态机 + LLM 消息生成

`synthetic_socio_wind_tunnel/conversation/dialogue_service.py` SHALL 定义
`DialogueService` 类：

```
schedule_invite(initiator_id, invitee_id, target_location_id, tick) -> Dialogue
accept_invite(dialogue_id, tick) -> bool      # invitee 接受
reject_invite(dialogue_id, reason, tick) -> None  # invitee 拒绝
advance(dialogue_id, tick, *, both_at_target: bool) -> DialogueStatus
                                                # invited → walking_over → participating
append_message(dialogue_id, message: DialogueMessage) -> None
end(dialogue_id, end_reason: str, tick) -> None
get(dialogue_id) -> Dialogue | None
active_for(agent_id) -> Dialogue | None
ended_for(agent_id, since_tick: int) -> list[Dialogue]
all_dialogues() -> list[Dialogue]
```

- 内部存储：`dict[dialogue_id, Dialogue]`
- 状态推进规则：
  - invited + accept_invite → walking_over（双方）
  - walking_over + advance(both_at_target=True) → participating
  - participating + max 8 messages 或 30 simulated minutes → 自动 end(reason="timeout")
  - participating + agent 主动 leave → end(reason="leave")
- service SHALL 提供 seeded RNG（init 参数 seed），用于 invite acceptance 决定

cooldown 规则：
- 同 pair (a, b) 在 24 simulated 小时内不重复 invite（除非 push 强触发）
- service 内部维护 `last_dialogue_ended_at[(a,b)]` 用于查询

#### Scenario: schedule + accept 走完正常路径

- **WHEN** schedule_invite("emma", "linda", "cafe", tick=10)；accept_invite(d_id, tick=11)
- **THEN** dialogue.status == "walking_over"；service.active_for("emma") 与 active_for("linda")
  返回同 dialogue

#### Scenario: 拒绝清理

- **WHEN** schedule_invite + reject_invite(d_id, reason="busy", tick=12)
- **THEN** dialogue.status == "ended"；end_reason == "rejected:busy"；不影响其它 dialogue

#### Scenario: cooldown 阻止重复

- **WHEN** dialogue (a, b) 在 tick=100 ended；尝试 schedule_invite(a, b, ..., tick=110)
- **THEN** schedule SHALL 拒绝（返回 None 或抛 CooldownError）；除非 force=True

#### Scenario: max messages 自动结束

- **WHEN** participating dialogue 累积 8 条 messages
- **THEN** advance 调用 SHALL 自动 end(reason="max_messages")

### Requirement: dialogue → memory + propagation 桥接

DialogueService SHALL 提供 `bridge_to_memory_and_propagation(dialogue_id, *, memory_service, conversation_service, social_graph) -> None`：

- 当 dialogue 结束时调
- **memory side**：双方各产一条 MemoryEvent[kind="encounter"]（含 dialogue summary 引用），
  importance 默认 0.7（高于 generic encounter 的 0.5）；具体 summary 由 remember_conversation
  op 异步填回
- **propagation side**：dialogue summary 包成 Information（category="dialogue", salience=0.6），
  调 conversation_service.record_origin(info, initiator_id, tick)；下 tick 起按概率向其它
  agent 扩散
- **social_graph side**：双方 record_encounter(a, b, tick, day_index)，强化 tie

#### Scenario: dialogue end 触发三层写入

- **WHEN** dialogue end → bridge_to_memory_and_propagation 跑
- **THEN** memory_service.record SHALL 被调 2 次（双向 encounter）；
  conversation_service.info_count() SHALL +1；social_graph.get_tie(a, b) SHALL 存在或 encounter_count +1

### Requirement: dialogue metrics

`DialogueService` SHALL 提供：

```
total_count() -> int
active_count() -> int
ended_count() -> int
avg_message_count() -> float
avg_duration_minutes() -> float
counts_by_end_reason() -> dict[str, int]
```

inspector / metrics 消费这些数据。

#### Scenario: metrics 反映状态

- **WHEN** 5 个 dialogue 结束（2 leave / 2 timeout / 1 max_messages）
- **THEN** total_count==5；ended_count==5；counts_by_end_reason == {"leave": 2,
  "timeout": 2, "max_messages": 1}
