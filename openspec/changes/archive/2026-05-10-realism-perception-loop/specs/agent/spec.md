## ADDED Requirements

### Requirement: Planner.replan 接收 perceptual_context

`Planner.replan` SHALL 接收一个新的 keyword-only 参数
`perceptual_context: SubjectiveView | None = None`。当传入非 None 时，replan
prompt SHALL 在 `【手机】` block 之后插入 `【环境】` block，描述 agent 当前
**看见的实体 / 听见的事件 / 闻到的气味** 的 lightweight prose 拼接。

prose 拼接规则：
- 同 location 的其它 agent 数 → "这里现在有 N 个人"
- visible_entities 中的 item（POI 招牌 / 海报 / 物品）→ 摘 1-3 条 content prose
- audible_events → 摘 1 条最近的 dialog snippet（如有）
- olfactory_descriptors → 1 句概述（如非空）

`perceptual_context = None` 时 `【环境】` block SHALL 整块省略，**保持现有
prompt shape 测试不破**（B7 之前的所有 replan prompt 测试继续 pass）。

`Planner.replan` 签名其余部分（返回 `tuple[DailyPlan, bool]`）SHALL 保持不变。

#### Scenario: 空 perceptual_context 不影响 prompt
- **WHEN** `Planner.replan(profile, plan, ctx)`（无 perceptual_context kwarg）
- **THEN** 生成的 prompt SHALL 不含 `【环境】` 字符串；现有 prompt structure
  测试 SHALL 全部 pass

#### Scenario: 提供 perceptual_context 时 prompt 含【环境】block
- **WHEN** `Planner.replan(profile, plan, ctx, perceptual_context=view)` 且
  view.visible_entities 非空
- **THEN** prompt SHALL 含 `【环境】` 字符串；视觉 / 听觉 / 嗅觉至少一个 sense
  的内容 SHALL 出现在该 block 的 prose 里

#### Scenario: 视觉密度信息进入 prompt
- **WHEN** view 的 visible_entities 包含 5 个 kind="agent" 的实体
- **THEN** prompt 的 `【环境】` block SHALL 含数字 "5" 与 "人" / "agent"
  之类描述，让 LLM 能 reasoning 关于 crowd

### Requirement: AgentRuntime.step 在 replan 触发前 render perception

`AgentRuntime.step(tick_ctx)` SHALL 在调用 `should_replan` 评估为 True 后、
在调 `planner.replan` 之前，先调用 `self._perception.render(observer_ctx)`
（其中 observer_ctx 来自 `self.build_observer_context()`），把得到的
`SubjectiveView` 作为 `perceptual_context` 传给 replan。

当 `self._perception is None`（perception 服务未注入），SHALL 跳过 render，
传 `perceptual_context=None`，**保持兼容现有 1190 测试基线**。

#### Scenario: 未注入 perception 时降级
- **WHEN** AgentRuntime 在没有注入 perception 服务的情况下触发 replan
- **THEN** SHALL NOT 抛错；SHALL 调用 planner.replan 时 perceptual_context=None

#### Scenario: 注入 perception 时 replan 真用 SubjectiveView
- **WHEN** AgentRuntime 注入 perception 服务，且本 tick 触发 replan
- **THEN** planner.replan 收到的 perceptual_context SHALL 是 SubjectiveView
  实例；其内容反映 ledger 当前状态（同 location 的 agent / atlas 中 location
  的 visible items）


### Requirement: Scripted plan 抵达后的 perception-gated destination-swap

为给 990 个 non-protagonist agent 也接入 perception，`AgentRuntime.step` SHALL
在以下条件**全部满足**时，触发"换 destination"行为：

1. agent 是 non-protagonist（`profile.is_protagonist == False`）
2. 当前 plan step 状态为 stay-arrived（已抵达 destination 进入停留阶段）
3. 注入了 perception 服务
4. 渲染 SubjectiveView 后，当前 location 上的同类 agent 数 >
   `crowd_threshold`（默认 5）
5. rng 随机数低于 `personality.openness × 0.5`（高 openness → 50% 触发率）

触发后：调用一个新 helper `agent.scripted_plan::perception_gated_destination_swap(
current_step, observer_ctx, rng, atlas, *, crowd_threshold=5)` 选一个**不同于
原 destination** 的 outdoor area 作为新 destination；改写当前 plan step 的
`destination` 字段并 reset `arrival_minute`。

helper 选 destination 规则：
- 优先选**同 area_type**（park 换 park / cafe 换 cafe）
- 距离当前位置 ≤ 1000m（hyperlocal 范围）
- 不选 home（home 不算 swap 候选）

未触发时（条件 4 / 5 失败），plan 继续原路径——保持现有 scripted_plan 行为。

#### Scenario: 拥挤触发 swap
- **WHEN** scripted agent 抵达 cafe_main，渲染 SubjectiveView 显示当前 location
  有 6 个 agent；agent.openness=0.8；rng 给出 0.3
- **THEN** 当前 plan step 的 destination SHALL 被改写为另一个 cafe 类
  outdoor_area；agent 的下一个 tick SHALL 启动新路径

#### Scenario: 不拥挤不触发
- **WHEN** 同上但 SubjectiveView 显示当前 location 只有 2 个 agent
- **THEN** plan step 不变；agent 继续 stay 阶段

#### Scenario: 低 openness 拥挤也不换
- **WHEN** 拥挤但 agent.openness=0.1
- **THEN** rng 触发概率 = 0.05；多数情况下不换 destination

#### Scenario: protagonist 不走此路径
- **WHEN** protagonist agent 抵达 cafe_main，crowd 也满
- **THEN** SHALL NOT 触发 perception-gated swap（protag 走 ai-town 决策树）


### Requirement: Agent perception inspector CLI

`tools/agent_perception_inspector.py` SHALL 提供 CLI 入口：

```bash
python3 tools/agent_perception_inspector.py \
    --seed <int> --agent <agent_id> --day <int> --tick <int>
```

输出 SHALL 包含：
- 标题行：agent_id @ day X tick Y (HH:MM)
- 当前 location（包括 atlas 中的人读名）
- visible_entities 列表（每条带 distance / kind / brief description）
- audible_events 列表（如有）
- digital_state 摘要（pending_notifications 数 / feed_bias / screen_time_today）
- JSON dump（机读，给后续 2.5D 沙盘 C3 inspector 消费）

CLI SHALL **不**调用真 LLM；**不**修改 ledger / atlas；纯只读。

#### Scenario: CLI smoke 输出结构
- **WHEN** `python3 tools/agent_perception_inspector.py --seed 42
  --agent a_42_0001 --day 0 --tick 0`
- **THEN** stdout 含 "a_42_0001 @ day 0 tick 0"；含 "Location:" 字符串；含
  "JSON:" 字符串；exit code 0

#### Scenario: 不存在的 agent 报错
- **WHEN** `--agent nonexistent_id`
- **THEN** exit code != 0；stderr 含 actionable 错误信息（不是 stack trace）
