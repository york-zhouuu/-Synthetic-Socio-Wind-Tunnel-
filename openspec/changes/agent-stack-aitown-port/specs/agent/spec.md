## ADDED Requirements

### Requirement: AgentProfile.identity_text / plan_text

`AgentProfile` SHALL 新增两个 optional 字段：

```
identity_text: str | None = None     # LLM-generated 一句话自我描述
plan_text: str | None = None          # LLM-generated 一句话当前生活规划
```

- 仅 protagonist agent 填这两个字段；scripted agent 保持 None
- 由 `population.sample_population` 在 protagonist 实例化时 batch LLM call 生成（一次性，frozen）
- 用于 dialogue / reflection 的 prompt 头部 system context

#### Scenario: scripted agent 默认 None

- **WHEN** profile.is_protagonist == False
- **THEN** identity_text SHALL == None；plan_text SHALL == None

#### Scenario: protagonist 在 sample 时填充

- **WHEN** sample_population(template, ..., generate_identity=True) 跑完
- **THEN** 所有 is_protagonist 的 profile 的 identity_text / plan_text SHALL 非空字符串

### Requirement: AgentRuntime ai-town 风格状态字段

`AgentRuntime` SHALL 新增以下字段（mutable）：

```
pending_operation: PendingOp | None = None
current_dialogue_id: str | None = None
to_remember: str | None = None             # dialogue_id；下 tick 触发 remember op
last_dialogue_ended_tick: int | None = None  # cooldown
last_op_kind: str | None = None             # 上次 op 类型，便于决策树循环避免
```

- 这些字段只在 protagonist runtime 上变化；scripted runtime 保持默认值
- frozen=False 但通过 dedicated mutator 方法变更（无直接 setattr 业务代码）

#### Scenario: scripted runtime 不动

- **WHEN** scripted agent 跑完 14 天
- **THEN** 所有 4 字段 SHALL 始终为默认值（None）

#### Scenario: protagonist dialogue 状态推进

- **WHEN** protagonist 进入 dialogue d1 → AgentRuntime.current_dialogue_id 设为 "d1"
- **THEN** 在 dialogue 结束前，agent.step 决策树 SHALL 走 dialogue 分支

### Requirement: AgentRuntime.step 决策树（ai-town port）

`AgentRuntime.step(tick_ctx)` SHALL 在 protagonist 路径下按以下决策树执行：

```
1. 消费 tick_inputs（async op 完成的 result）
   - if remember_op done: 写 memory；clear to_remember
   - if reflect_op done: 写 reflection memory
   - if generate_message done: 把 message 写进 dialogue.messages

2. 如果 pending_operation 非空 且 未 timeout：
   → return WaitIntent(reason="awaiting_op")

3. 如果 to_remember 非空：
   → schedule remember_conversation op
   → return WaitIntent(reason="will_remember")

4. 如果 current_dialogue_id 非空：
   - dialogue.status == "walking_over": MoveIntent toward partner location
   - dialogue.status == "participating" 且 该自己说话:
     → schedule generate_message op
     → return WaitIntent(reason="composing")
   - dialogue.status == "participating" 且 等对方:
     → return WaitIntent(reason="listening")
   - dialogue.status == "ended":
     → set to_remember = dialogue_id; clear current_dialogue_id
     → continue to step 5

5. 如果 plan 提供有效 step 且未过期：
   → 走 plan-driven Intent（既有逻辑，MoveIntent / WaitIntent / etc.）

6. 如果 plan 卡住 / 没下一步 / 长时间 wait：
   → schedule do_something op
   → return WaitIntent(reason="reconsidering")
```

scripted agent 跳过 1-4 + 6，走纯 plan-driven 路径（既有逻辑，不变）。

#### Scenario: pending op 时不前进

- **WHEN** protagonist runtime 有 pending_operation；跑 step()
- **THEN** SHALL return WaitIntent(reason="awaiting_op")

#### Scenario: dialogue walking_over 时去找对方

- **WHEN** protagonist current_dialogue_id="d1"，d1.status=walking_over，partner 在 location_x
- **THEN** SHALL return MoveIntent(to_location="location_x")

#### Scenario: scripted agent 行为不变

- **WHEN** scripted agent（is_protagonist=False）跑 step
- **THEN** SHALL 跟 ai-town port 之前完全一样（仅走 plan-driven 路径）

#### Scenario: dialogue end 后下 tick 触发 remember

- **WHEN** dialogue d1 status 变为 "ended" 在 tick T；agent.step T+1 跑
- **THEN** SHALL schedule remember_conversation op；返回 WaitIntent(reason="will_remember")

### Requirement: AgentRuntime feature flag

`AgentRuntime` SHALL 接受构造参数 `use_aitown_decision_tree: bool = False`：

- False（默认）：所有 agent 走纯 plan-driven 路径（向后兼容；现有
  990 scripted + 老的 10 protagonist 测试不受影响）
- True：仅 protagonist 走 ai-town 决策树；scripted agent 仍走旧路径
  （`is_protagonist` 与此 flag 同时为 True 才启用）
- 实例化 protagonist 时由调用方（典型为 population layer 或测试）显式
  设置为 True，避免协议变更影响默认 fixture

#### Scenario: feature flag 关闭时退回老路径

- **WHEN** 构造 AgentRuntime(use_aitown_decision_tree=False)
- **THEN** step() SHALL 行为等同 ai-town port 之前；pending_operation /
  current_dialogue_id 字段忽略

#### Scenario: scripted agent 即使 flag 开也走老路径

- **WHEN** 构造 AgentRuntime(profile=scripted_profile, use_aitown_decision_tree=True)
- **THEN** step() SHALL 走 legacy 路径（`profile.is_protagonist=False`
  时 ai-town 分支被跳过）

## MODIFIED Requirements

### Requirement: Population 采样子模块

系统 SHALL 在 `synthetic_socio_wind_tunnel/agent/population.py` 提供
`sample_population(profile, *, seed, num_protagonists, home_locations,
generate_identity=False, llm_client=None)`，采样 N 个 AgentProfile。

字段：
- 既有：person 的 19 维 + personality + LifePattern + is_protagonist 布尔
- **新增**：当 `generate_identity=True` 且 `is_protagonist=True` 时，每个 protagonist
  SHALL 通过 batched LLM call 生成 `identity_text` 和 `plan_text`
- 每条 prompt SHALL 基于 profile 的 19 维 + LifePattern 让 LLM 输出一句话自我描述 + 一句话当前规划
- LLM call SHALL 使用 `llm_client` 参数；失败 SHALL fallback 到 None（不阻塞 sample）

成本预算：
- 每 protag ~80 tokens prompt + ~50 tokens completion
- 100 protag ~ 13000 tokens ≈ $0.1（sonnet）

#### Scenario: generate_identity=False 时不调 LLM

- **WHEN** sample_population(... generate_identity=False)
- **THEN** identity_text / plan_text SHALL 全部为 None；不调任何 LLM

#### Scenario: generate_identity=True 时填充

- **WHEN** sample_population(... generate_identity=True, llm_client=mock_llm,
  num_protagonists=10)
- **THEN** 10 个 protag 的 identity_text / plan_text SHALL 全非空；llm_client.generate
  SHALL 被调用 10 次（或单 batched 调用）；scripted agent 仍 None

#### Scenario: LLM 失败 fallback

- **WHEN** llm_client.generate 抛异常
- **THEN** identity_text 设为 None；不阻塞 sample（继续生成下一 agent）；warning 记录
