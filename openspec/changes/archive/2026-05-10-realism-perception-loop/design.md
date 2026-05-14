## Context

`docs/agent_system/20-realism-roadmap.md` Stage 2 + `docs/agent_system/21-current-agent-design.md`
都识别了同一缺口：**PerceptionPipeline 是死代码**。完整实现了视觉 / 听觉 /
嗅觉 / digital_attention 滤镜，但**没有一个决策路径在调它**。

具体 audit：
- `synthetic_socio_wind_tunnel/agent/runtime.py:944` `build_observer_context()`
  拼装 ObserverContext —— 但整个 codebase grep 只有 perception 自检测试在调它。
- `synthetic_socio_wind_tunnel/agent/scripted_plan.py::build_scripted_plan` 不读
  perception；纯 deterministic time-of-day → destination 模板。
- `synthetic_socio_wind_tunnel/agent/planner.py::_build_replan_prompt` 6 个 block
  （`【现在】/【正在做】/【周围】/【最近发生】/【手机】/【接下来计划】`）
  —— `【周围】` 名字像 perception，但实际只是 `nearby_agents` 列表（来自
  encounter detection），不是 perception 输出。

约束：
- 不破坏现有 1190 passed 测试基线
- `Planner.replan` 已经是 `tuple[DailyPlan, bool]` 返回（B7 fix），新参数走 kwarg
- scripted_plan 是 990 个 agent 的热路径，性能要求严：每 tick × 1000 agent 不
  能多花超过 ~50ms 总额外开销
- thesis 链路：本 change 不改 hp / gd / pf variant，但要让它们的下游"看见"环节真活

利益相关者：
- thesis 答辩（A1 是因果链最后一环，必做）
- 2.5D 沙盘 C3 inspector（依赖本 change 产出 SubjectiveView 文本接口）
- 后续 ai-town path 给 do_something / generate_message 加感知（依赖本 change
  把"感知接进 prompt"的模板形成）

## Goals / Non-Goals

**Goals:**

1. `Planner.replan` 在收到 perceptual_context 时，prompt 增加 `【环境】` block
   描述 agent 实际看见 / 听见的场景（不只 nearby_agents）。
2. `AgentRuntime.step` 在 replan 触发前 render perception 一次，结果传给 replan
   作为新 kwarg。
3. `scripted_plan` 的 990 个非-protag agent 也加一层 lightweight perception
   gate：抵达 destination 时若 crowded（visible_entities 同 location agent > 5），
   按 `personality.openness` 概率换 destination。
4. 新 `tools/agent_perception_inspector.py` CLI：`--seed --agent --day --tick`
   出 SubjectiveView 文本快照，供 debug + 后续沙盘 C3 inspector。
5. 全量 regression 不退；新增 ≥ 4 contract test。
6. 1 seed × 1 day × 20 agent smoke 验证：至少 1 个 protag 的 replan prompt 真
   含 `【环境】` block；至少 1 个 scripted agent 因 crowd-gate 换了 destination。

**Non-Goals:**

- 不动 `perception` capability 内部（滤镜 / SubjectiveView 数据结构）
- 不改 ai-town path 的 do_something / generate_message handler（那是 ai-town
  port 后续 task 范围）
- 不重跑 publishable suite（smoke 即可）
- 不引入新 LLM 调用（perception 是本地 deterministic 渲染）
- 不在 `Planner.generate_daily_plan` 加 perception（那是"今早起床"场景，无
  perception 输入；本 change 只动 replan + arrival check）

## Decisions

### Decision 1：Planner.replan 用 kwarg 接 perceptual_context（非 breaking）

**Why**：B7 已经把 replan 签名改成 `tuple[DailyPlan, bool]` 返回；再硬改一次
position-arg 会让所有 caller 二次更新。kwarg 默认 None 兼容现有 caller
（`memory.process_tick` 不传，行为不变）。

**How**：

```python
async def replan(
    self,
    profile: AgentProfile,
    current_plan: DailyPlan | None,
    interrupt_ctx: dict[str, Any],
    *,
    perceptual_context: "SubjectiveView | None" = None,
) -> tuple[DailyPlan, bool]:
    ...
    prompt = _build_replan_prompt(
        ...,
        perceptual_view=perceptual_context,  # ← 新
    )
```

`_build_replan_prompt` 在 `【手机】` 之后插入新 block：

```
【环境】这里现在的样子：cafe_main 桌位约 5 / 8 满；窗外街上人不多；隔壁书店灯还亮着。
```

文本来自 `SubjectiveView` 的 `visible_entities` + `audible_events` + `olfactory_*`
的 lightweight prose 拼接。空 SubjectiveView → 整块省略（保持现有 prompt
shape 测试不破）。

**备选**：往 `interrupt_ctx` dict 里塞 perceptual_context（不动签名）。否决：
interrupt_ctx 本来已经是 6 个 key，再加会让 Planner.replan 接口"什么都能塞"，
失去类型契约；显式 kwarg 更清晰。

**风险**：[Risk] perception render 在每次 replan 时都跑，增加 ~5-10ms / call。
1000 agent × 14 day × 平均 3 replan/day = 42K render → ~300s 累计。Mitigation：
perception 是 deterministic 缓存友好的；如果性能问题，可以在 SubjectiveView 加
`render_cache_key`。

### Decision 2：AgentRuntime.step 在 replan 触发前 render 一次 perception

**Why**：调用方便 + 单一入口。现在 `should_replan` 在 `memory.process_tick`
里被调用；而 perception render 应该是 AgentRuntime 自己的事（agent 自检"我
现在看见什么"）。

**How**：在 `AgentRuntime.step` 的 replan 决策分支前：

```python
def step(self, tick_ctx) -> Intent:
    ...
    if self.should_replan_now(...):
        observer_ctx = ObserverContext(**self.build_observer_context())
        view = self._perception.render(observer_ctx) if self._perception else None
        # view 通过 interrupt_ctx 间接 / 通过新 attr 直接 → 待 D1 决定
        ...
```

**备选 D1**：`memory.process_tick` 在调 `planner.replan` 前 render。否决：
memory 不该负责 perception；single responsibility 违反。

**备选 D2**：把 `_perception` 注入 Planner 内部，让 Planner 自己 render。否决：
Planner 是 pure function（不持有 sim state），改这个会破坏现有架构。

**选 Decision 1**：runtime 是唯一持有 `self._perception` 引用且能调
build_observer_context 的地方。

**风险**：[Risk] 现有 AgentRuntime 不一定都注入了 perception 服务。Mitigation：
guard `if self._perception is not None`，None 时降级为 perceptual_context=None
（行为兼容现有测试）。

### Decision 3：scripted_plan 的 perception-gated destination-swap

**Why**：990 个 scripted agent 不走 LLM replan，只走 deterministic 路径。如果
不给它们也加一层感知触达，**只有 10 个 protag 受益于 A1**——baseline encounter
density 不会改善，hp 的相对差异仍是只在 10 个 protag 上算。

**How**：在 scripted_plan 抵达 destination 后（即 step 的 stay 阶段开始时），
runtime 调一个新 helper：

```python
# 在 AgentRuntime.step 的 stay-arrived 分支
if not self.profile.is_protagonist:
    swap_dest = perception_gated_destination_swap(
        current_step=self.plan.current(),
        observer_ctx=...,
        rng=...,
        crowd_threshold=5,
        openness=self.profile.personality.openness,
    )
    if swap_dest:
        # 当前 step 改 destination；不走 LLM
        ...
```

`perception_gated_destination_swap`:

```python
def perception_gated_destination_swap(
    *, current_step, observer_ctx, rng, crowd_threshold=5, openness=0.5,
) -> str | None:
    """If current location crowded above threshold AND agent is open enough,
    return alternative destination from atlas; else None.

    crowded = len([e for e in view.visible_entities if e.kind == "agent"
                   and e.location_id == current_step.destination]) > threshold
    p_swap = openness * 0.5  # high openness → 50% swap when crowded
    """
```

**备选**：让 scripted_plan **生成时**就考虑 perception。否决：plan 在 day-start
生成，那时还没 simulation tick，看不到运行时 crowd。必须 runtime 时检查。

**性能预算**：每 tick × 990 agent × ~30% 处于 stay 阶段 = ~300 调用 /tick。
每次 perception render ~5ms → 1.5s/tick × 288 tick/day × 14 day = ~6 分钟额外。
可接受（publishable run 总时长 12-15 hr，6 分钟是 < 1%）。

### Decision 4：inspector CLI 用文本输出（不做 GUI）

**Why**：A1 不是 2.5D 沙盘。inspector 在 A1 阶段是**debug + 后续沙盘 C3
的数据源**。文本输出直接喂下次 sandbox 工作，不用先做 UI。

**How**：

```bash
$ python3 tools/agent_perception_inspector.py \
    --seed 42 --agent a_42_0001 --day 3 --tick 144
```

输出（人读 + JSON dump）：
```
=== a_42_0001 @ day 3 tick 144 (12:00) ===
Location: cafe_main (Cowper Street segment 1)
Visible entities (4):
  - a_42_0007 (1m away, kind=agent, gender=female, age_bucket=30-39)
  - bench_3 (5m, kind=item)
  - poster_community_run (8m, kind=item, content="Lane Cove community run...")
  - a_42_0123 (12m, kind=agent, ...)
Audible events:
  - dialog at 4m: "...今天人挺多" (speaker=a_42_0007)
Digital state:
  - pending_notifications: 0
  - feed_bias: local
  - screen_time_today: 0.8h / 4h
JSON: {"visible_entities": [...], ...}
```

## Risks / Trade-offs

- **[Risk]** 修了 A1 之后 hp 的 encounter 信号会再次抖动（990 scripted agent
  也开始有 perception-gated swap），realism test 阈值可能再次需要校准 →
  Mitigation：smoke 验证后看哪些 test 失败，按 round-2 同款方式校准。
- **[Risk]** scripted_plan 加 perception-gated swap 后 plan 不再纯 deterministic
  → reproducibility 取决于 rng + perception render 的稳定性。Mitigation：
  perception 已经是 deterministic（不调 LLM），rng 在 runtime.step 里 seed 一致；
  应该仍 byte-identical。新增一个 reproducibility test 验证。
- **[Trade-off]** Decision 3 的 `crowd_threshold=5` 是魔术数。可调；写死在 helper
  里，未来若需 personality-driven 阈值再迭代。
- **[Risk]** Planner.replan 加 `【环境】` block 后 prompt token 数上涨（~50-100
  tokens 每 call）→ Gemini cost 微涨。Mitigation：B6 token tracking 已 ship，
  smoke 后看 cost_breakdown 增量是否可接受。

## Migration Plan

1. 先改 spec delta（`agent` capability）+ 本 design 通过 review。
2. 实施 Decision 4（inspector CLI）—— 最小、独立、零回归风险，先合。
3. 实施 Decision 1（Planner.replan kwarg + prompt block）+ Decision 2
   （AgentRuntime.step render perception）—— 一起合，两者强耦合。
4. 实施 Decision 3（scripted_plan crowd-gated swap）—— 单独合，影响 990 agent
   行为。
5. 1 seed × 1 day × 20 agent smoke 验证。
6. 全量 regression 必须 ≥ 1190 passed；如果 realism test 因 swap-rate 偏移失败
   按 round-2 同款方式校准阈值。
7. 走通后归档。

## Open Questions

1. `crowd_threshold=5` 的合理值？—— 默认 5 先做；smoke 后看是否需要按 cafe /
   street / park 分 area_type 给不同阈值。
2. `perceptual_context` 在 replan prompt 中的语言风格？—— 倾向中文 prose 描述
   （与现有 prompt 风格一致），不是 raw dict。
3. inspector CLI 输出 schema 要不要正式化为 JSON schema？—— 暂不正式化；A1
   阶段是 debug 工具，等 C3 沙盘 inspector 启动时再 schema 化。
