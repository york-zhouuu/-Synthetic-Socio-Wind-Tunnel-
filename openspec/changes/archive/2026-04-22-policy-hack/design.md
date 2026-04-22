## Context

`experimental-design` spec（`openspec/specs/experimental-design/spec.md`）规定：
- 每 primary experiment SHALL 绑定一个 hypothesis 到一个 variant
- Suite 至少 4 条 cross-class variant + 1 paired mirror
- 14-day Baseline(4)/Intervention(6)/Post(4) 协议
- β 严谨度：30 seed × IQR/CI

`multi-day-simulation` 提供执行基建：`MultiDayRunner` 的 `on_day_start` /
`on_day_end` hook 给外部注入 phase 逻辑；`MultiDayResult.metadata` 预留给
实验数据。但**没有 variant 抽象 / 没有 phase 控制器 / 没有具体干预实现**。

当前 `attention-channel` 提供底层通道（`FeedItem` / `NotificationEvent` /
`AttentionService.inject_feed_item`）；`agent` 提供 `DigitalProfile` / population
sampling；`orchestrator` 提供 tick loop。但这些是**原材料**，不是实验。

干预类型（来自 Brief v1 §4.4）：5 类 policy hack——info injection / space
unlock / object placement / task assignment / perception modification。
v2 thesis 收敛后，所有 5 类都归到 `algorithmic-input` 层（见
`docs/agent_system/03-干预机制与实验指标.md`）。本 change 实现的 4 primary
variant 分别是：
- A Hyperlocal Push → **info injection**
- B Phone Friction → **perception modification**（改 digital filter 行为）
- C Shared Anchor → **task assignment**
- D Catalyst Seeding → 不是单次干预；是**人群结构层**的种子
- A' Global Distraction → **info injection**（攻击向）

空间干预（space unlock）在 Lane Cove OSM 当前数据下 skip，不在本 change
实现（见 fitness-audit `e2.*` 结果）。Object placement 亦 skip。

## Goals / Non-Goals

**Goals**:
- 提供统一 `Variant` 抽象：4 + 1 variants 使用同样生命周期 API，CLI /
  报告 / 测试可复用
- 抽离 `PhaseController`：Baseline/Intervention/Post 切换是可复用组件，
  不是 per-variant 重写
- 每 variant 内置 `metadata` 字段：绑定 hypothesis / theoretical_lineage /
  success_criterion / failure_criterion（`experimental-design` spec 要求）
- CLI 一行切 variant：`--variant hyperlocal_push` 等
- 性能：干预不引入 LLM 调用；模板化 feed 生成

**Non-Goals**:
- 不实现 metrics 算法（`metrics` change 的事）
- 不实现 B'/C'/D' mirror（experimental-design Appendix A 文档化）
- 不引入 LLM-generated feed content（template-based，reproducibility 优先）
- 不处理 variant 组合（rival contest 是横向对比）
- 不向 attention-channel / agent / multi-day-run 加 spec 修改

## Decisions

### D1：`Variant` 是抽象基类 + 混入 Pydantic

**选择**：`Variant` 是 `abc.ABC` 抽象基类；每具体 variant 同时用 Pydantic
frozen model 来持有 config（为了 CLI 参数化 + JSON dump）。

**备选**：
- 纯 `dataclass(frozen=True)` — 不够灵活，没有 runtime validation
- 纯 Pydantic — 没有 abstract method enforcement
- ✓ ABC + Pydantic 混合：每 variant 定义为 `BaseVariant(BaseModel, ABC)`
  的子类；模型字段 holds 参数，抽象方法定义生命周期

**原因**：与项目整体（`AgentProfile` / `FeedItem` 等 Pydantic 风格）一致；
又保留子类必须实现关键方法的静态保证。

### D2：Variant 生命周期三钩子

**选择**：
```python
class Variant(BaseModel, ABC):
    @abstractmethod
    def apply_population(self, profiles, rng) -> list[AgentProfile]: ...
    @abstractmethod
    def apply_day_start(self, ctx: VariantContext) -> None: ...
    def apply_day_end(self, ctx: VariantContext) -> None: ...  # default no-op
```

**为什么三钩子**：
- `apply_population`: D (Catalyst Seeding) 需要——其它 variant 默认
  `return profiles`（无操作）
- `apply_day_start`: A/A'/C 的每日 push 注入、B 的每日 friction 应用点
- `apply_day_end`: 可选——给需要清理一次性 state 的 variant 用（当前无
  variant 需要，但 B' 未来若做会用到）

**备选**：只 `apply_day_start`——但 D 的 population 操作在 run 前一次性，
跟 day_start 语义不同；不混入更干净。

### D3：`PhaseController` 是独立组件

**选择**：
```python
class PhaseController(BaseModel):
    baseline_days: int = 4
    intervention_days: int = 6
    post_days: int = 4

    def phase(self, day_index: int) -> Literal["baseline", "intervention", "post"]: ...
    def is_active(self, day_index: int) -> bool: ...  # True iff phase == intervention
```

**原因**：
- `experimental-design` spec 规定 14-day protocol，但 dev mode 允许
  3-day 缩减——phase 控制器参数化支持两档
- 多个 variant 跑同一 phase 控制器；不让 Variant 自己知道 phase

### D4：`VariantRunnerAdapter` 挂接 MultiDayRunner

**选择**：
```python
class VariantRunnerAdapter:
    def __init__(self, variant: Variant, controller: PhaseController): ...

    def attach_to(self, runner: MultiDayRunner) -> None:
        """一行注入 on_day_start / on_day_end hook。"""
```

**为什么 adapter**：
- MultiDayRunner 的 hook 签名是 `(date, day_index) -> None`——没有 variant/
  controller 概念
- Adapter 捕获两者，内部构造 `VariantContext(day_index, date, ledger,
  attention_service, agents, runtimes)` 传给 variant 的 `apply_day_start`
- `VariantContext` frozen dataclass，明示 variant 能访问什么

**不引入**：MultiDayRunner 不加 variant 参数——保持 multi-day-run spec
契约不变；policy-hack 是纯客户端

### D5：variant 的 metadata 跟 variant 一起

**选择**：
```python
class Variant(BaseModel, ABC):
    name: str                    # "hyperlocal_push"
    hypothesis: Literal["H_info", "H_pull", "H_meaning", "H_structure"]
    theoretical_lineage: str     # "Shannon + Wu attention economy"
    success_criterion: str       # "evidence consistent with H_X when ..."
    failure_criterion: str       # ...
    chain_position: Literal["algorithmic-input", "attention-main", ...]
    is_mirror: bool = False
    paired_variant: str | None = None   # for mirrors

    def metadata_dict(self) -> dict: ...  # JSON-dump ready for MultiDayResult.metadata
```

**原因**：`experimental-design` spec 要求每 variant 声明这些字段；定义在
基类保证静态检查 + 方便 CLI / 报告 pipeline 读取

### D6：A/A' feed content 模板化

**选择**：两变体持有 `content_templates: tuple[str, ...]` + `target_params`；
每日 push 时从模板随机选（seed-bound RNG）并填入 `{location}` / `{agent_name}`
等占位符。

**备选**：
- 硬编码单一消息——无变化，可能被 agent "适应"
- LLM 生成——违反 Non-goal；reproducibility 跨 seed 失效

**原因**：模板化在足够多样化 vs 完全 reproducible 之间平衡。每 seed 同样
RNG 序列 → 同样 content，便于 bug repro；不同 seed 有 content 多样性。

### D7：B (Phone Friction) 通过直接改 AgentProfile.digital

**选择**：`PhoneFrictionVariant.apply_day_start` 在 intervention phase
第一天**一次性**把每个 agent 的 `DigitalProfile.screen_time_hour *= 0.5`
（或参数化倍数）——post phase 恢复。

**备选**：
- 每 tick 改——过于频繁；违反"每日一次决策"的 MultiDayRunner 精神
- 改 digital_attention filter 的参数而非 DigitalProfile——更优雅，但
  该 filter 当前从 profile.digital 读值，所以改 profile 也等价

**问题**：AgentProfile 是 frozen——直接改会报错。方案：**在 Variant 内部
为每个 agent 构造替换版 profile，更新 agent.runtime.profile 字段**。
agent.runtime.profile 非 frozen 指针，只是类型提示；可替换。

**post phase 恢复**：`PhoneFrictionVariant.apply_day_end` 在 last
intervention day 时恢复——需要 controller 知道"上次是不是 last"，或
variant 自己缓存原值。选后者：variant holds `_original_profiles: dict[str, DigitalProfile]`
字典，phase 切到 post 时恢复。

### D8：C (Shared Anchor) 通过 task-category feed + 共享 recipients

**选择**：`SharedAnchorVariant` 在 intervention phase 每日 start 调用
`AttentionService.inject_feed_item(feed_item, target_agent_ids)` 把**同一
feed_item_id**发给预定义的一组 agent（10% of population，seed-bound）。
feed_item.category = "task"；MemoryService 会把它 kind="task_received" 写入
memory；planner 的 `CarryoverContext.pending_task_anchors` 会把它列入次日
prompt。

**原因**：利用已有基建——不新建状态机。"共享"属性在数据层是"同一 feed_item_id
被 delivered 给多人"。

### D9：D (Catalyst Seeding) 通过 population sampler 包装

**选择**：`CatalystSeedingVariant.apply_population(profiles, rng)` 把传入
`profiles` 的 **5% agents** 的 personality 字段**覆盖**为 `catalyst_personality`
预设（高 extraversion / 低 routine_adherence / 高 curiosity）。

**备选**：重新采样（从 PopulationProfile 生成新的 5%）——不可——这改变了
其它字段分布，不是"只改 personality"
✓ 覆盖法：保留年龄 / 职业 / tenure 等其它维度不变，只针对 personality

**选多少人被 override**：默认 5%，参数化可调 0.01-0.10

### D10：CLI dispatch 通过 variant registry

**选择**：policy_hack 模块暴露 `VARIANTS: dict[str, type[Variant]]`
registry；`tools/run_multi_day_experiment.py` 根据 `--variant` 字符串查表
实例化。

```python
VARIANTS = {
    "hyperlocal_push": HyperlocalPushVariant,
    "global_distraction": GlobalDistractionVariant,  # mirror
    "phone_friction": PhoneFrictionVariant,
    "shared_anchor": SharedAnchorVariant,
    "catalyst_seeding": CatalystSeedingVariant,
}
```

**原因**：未来第三方 variant 可以 register（`VARIANTS["my_custom"] = ...`），
CLI 自动支持——无需改 CLI 代码

### D11：CLI 用 variant-specific YAML / JSON config（可选）

**选择 defer**：第一版 CLI 只支持预设 variant（构造参数走默认值）；
未来若需参数扫描（例如测试 "hyperlocal_push 推送频率 1 vs 5 vs 20/day"）
再加 `--variant-config config.yml`。当前本 change 不做。

**原因**：spec 中 Primary suite 是 **4+1 fixed variants**，不是参数扫描。
参数扫描属于 `metrics` change 或专门的 ablation study。

## Risks / Trade-offs

**[Risk 1] Variant 数据类 + 抽象方法导致 Pydantic 验证与 ABC 冲突**
→ 缓解：测试 `TestVariantCannotInstantiate` 验证 ABC 语义正确（试图
实例化 `Variant` 抽象类 SHALL raise TypeError）；参考 Pydantic 文档
`allow_inheritance` 模式。

**[Risk 2] `apply_population` 改 profiles 后 orchestrator 不知道新 personality**
→ 缓解：policy_hack 约定"先 apply_population → 再构造 orchestrator"，
顺序写进 `VariantRunnerAdapter.setup_run()` 辅助方法；测试覆盖

**[Risk 3] Phone Friction 的 profile 覆盖违反 frozen 约束**
→ 缓解：AgentProfile 是 Pydantic frozen——用 `.model_copy(update={...})`
构造新实例；`AgentRuntime.profile` 引用替换为新实例（runtime.profile 指针
非 frozen）

**[Risk 4] Shared Anchor 的"共享"属性在 multi-seed 下 seed 碰撞**
→ 缓解：shared_agent_ids 基于 seed 选择：同一 seed 永远选同样 10% 作为
"共享组"；不同 seed 选不同组——符合 cross-seed robustness

**[Risk 5] Global Distraction 推 20 条/day 可能撑爆 memory**
→ 缓解：100 agent × 20 push × 14 day = 28,000 notification events；每 event
~200 字节 → 5.6 MB per agent 量级的 memory footprint。实际 store 是 per-agent
独立 dict，单 agent 上限 ~20 × 14 = 280 events → 56 KB 级别。可接受

**[Risk 6] Variant 的 metadata_dict() 字符串全中文 → CI JSON dump 非 ASCII**
→ 缓解：ensure_ascii=False 已是项目默认（见
`tools/run_multi_day_experiment.py`），不需额外处理

**[Risk 7] CLI 接口变化破坏已归档的 smoke demo**
→ 缓解：`--variant baseline` 保留为"no variant applied"行为——与归档前
一致；测试回归覆盖

## Migration Plan

1. 新增 policy_hack 模块 + 5 个 variant 文件 + 基础抽象
2. 扩展 CLI dispatch（`--variant` 字符串查 VARIANTS registry）
3. `tools/run_variant_suite.py` 作为更方便的 suite runner
4. 测试逐个 variant 覆盖 + 集成测试
5. fitness-audit 自动 PASS 验证
6. 文档：`docs/agent_system/15-policy-hack.md` canonical

**回滚**：完全可回滚——policy_hack 是独立模块，delete 目录 + CLI 恢复
pass-through 即可；核心基建（orchestrator/memory/multi-day-run）不受影响

## Open Questions

1. **Q1**: `HyperlocalPushVariant` 应该每日推送 **1 条** 还是 **3-5 条**？
   倾向：默认 1 条/day（模拟"每日一条社区通知"的 baseline）；参数化允许
   {1, 5, 20}——但参数扫描留给未来 `metrics` change 或 ablation study；
   本 change 只需一个合理默认。
2. **Q2**: Shared Anchor 的 "task_description" 是否针对每 seed 变换？
   倾向：每 seed 随机从模板池选一个（例 "find the lost cat" / "spot the
   street art" / "leave a mark on community wall"），记入 metadata
3. **Q3**: Catalyst Seeding 的 5% 是否必须刚好 5，还是 "at least 5%"
   即可？
   倾向：ceil(0.05 × N) —— 100 agent → 5 catalyst；50 agent → 3 catalyst
4. **Q4**: `apply_population` 是否应该返回"新 profiles list"而非原地
   修改？
   倾向：**返回新 list**（D2 签名已定 `-> list[AgentProfile]`）；避免
   hidden 副作用；与 Pydantic frozen 设计一致
