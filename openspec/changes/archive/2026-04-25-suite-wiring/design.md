## Context

`metrics` archive 后的 smoke 显示 `run_variant_suite.py` 的 orchestrator 栈
没拼完：AttentionService inject 的 feed_item 进了 channel，但没有
`MemoryService.process_tick` 消费，也没有 `agent.should_replan` /
`planner.replan` 被触发；agents 一直跑 scripted plan，variant 行为无差。

已有零件（归档 capability 提供）：
- `AttentionService.inject_feed_item(item, recipients)` — policy-hack 已用
- `MemoryService.process_tick(tick_result, agents, planner=None)` — memory
  capability 主入口，内部调 `agent.should_replan(events, candidate)` + 
  `planner.replan(profile, plan, ctx)`
- `AgentRuntime.should_replan` — typed-personality 之后的纯代码规则
  （读 profile.personality.routine_adherence + curiosity）
- `Planner.replan(profile, current_plan, interrupt_ctx)` — memory change
  落地的 1-LLM-call replan（LLM 失败 fallback）

缺的：在 CLI 层把这些**装进**同一个 orchestrator hook 链。

约束：
- 不改已归档 capability 的 spec 契约
- 不引入 numpy/pandas（延续 metrics 的 lean）
- 默认零 LLM 调用（StubReplanLLM 承担 reproducibility）

## Goals / Non-Goals

**Goals**
- 让 variants 真正影响 agent 行为：至少 hyperlocal_push 与 global_distraction 
  产生**方向相反**的 trajectory_deviation_m delta
- Metrics smoke 产出非 byte-equal 的 per-variant 数字（证明 wiring 通）
- 提供 `--use-real-llm` opt-in 路径，让未来做真实 LLM 校准时 drop-in

**Non-Goals**
- 不改 Planner / Memory / AttentionService / Variant / MultiDayRunner 的 API
- 不做 cost 控制（model-budget 的事）
- 不扩展 RunMetrics 的 typed 字段（用 extensions dict）
- 不引入 LLM provider 抽象（直接 import anthropic）

## Decisions

### D1：StubReplanLLM 放在 tools/，不进 package

**选择**：`tools/suite_stub_llm.py`

**备选**：
- 进 `synthetic_socio_wind_tunnel/agent/stub_llm.py` ——production code 里
  放 stub 不合规（项目 CLAUDE.md 规定 "生产代码路径不得含 mock_ / demo_"）
- 进 `tests/` ——会被排除于生产构建，CLI 不能 import

**原因**：tools/ 是 CLI 位置，与 `run_variant_suite.py` 同目录便于 import；
且不误入 package 公共 API。

### D2：Stub 按 FeedItem.origin_hack_id 分派，不靠 content 解析

**选择**：
```python
class StubReplanLLM:
    async def generate(self, prompt: str, *, model: str = "", **_) -> str:
        # 从 prompt 里提取 origin_hack_id（policy-hack 已经把它塞进每条
        # feed_item）和 trigger event 的其它字段
        hack_id = _extract_origin_hack_id(prompt)
        if hack_id == "hyperlocal_push":
            return _plan_toward_location(self._target_location, self._rng)
        elif hack_id == "global_distraction":
            return "[]"  # 不改变 plan — 证明 global news 对 scripted 路径无拉力
        elif hack_id == "shared_anchor":
            return _plan_toward_location(self._shared_location, self._rng)
        return "[]"  # 未知触发或无触发
```

**备选**：
- 正则解析 content 找 "500m" / "巷子里" 等关键词 —— 脆弱，content 是自然
  语言模板；每次 variant 改模板都要更新 stub
- 让 Variant 基类暴露 `stub_replan_response()` 钩子 —— 污染 Variant 职责
  （Variant 不该知道 replan 怎么生成）

**原因**：`origin_hack_id` 是 policy-hack 已经写入的结构化字段（FeedItem
字段），稳定可查；变 content 不变字段；variant 加字段不影响 stub。

### D3：Prompt 里能读到 origin_hack_id 吗？

**验证**：Planner 的 replan prompt（见 `agent/planner.py::_build_replan_prompt`）
把 trigger_event 的 content + memory events 渲染进 prompt。需要让 prompt
**显式包含 origin_hack_id** 才能让 stub 按它分派。

**实施**：Stub 不依赖 Planner 改 prompt；改为让 stub 接受 `dispatch_fn`，由
`run_seed_with_metrics` 构造时注入——stub 自己知道当前 run 的 variant 身份。

**更新的签名**：
```python
class StubReplanLLM:
    def __init__(
        self, *,
        seed: int,
        variant_name: str,               # CLI 构造时注入
        target_location: str | None,      # 从 variant 或 CLI 传入
    ): ...
```

这样 stub 不需要解析 prompt——它从构造参数就知道该产什么。prompt 本身
只用来 satisfy LLM client 协议。

### D4：何时构造 MemoryService

**选择**：每 seed 一个 MemoryService 实例（run 内共享，跨 seed 独立）。

**原因**：MemoryService per-agent MemoryStore 不跨 run 持久；每 seed 新构
保证 reproducibility + state 隔离。

### D5：real LLM 切换

**选择**：
```python
def _make_llm_client(*, use_real: bool, variant_name, target_location, seed) -> LLMClient:
    if use_real:
        try:
            from anthropic import Anthropic
        except ImportError:
            sys.exit("--use-real-llm requires `pip install anthropic`")
        return _AnthropicClient(model="claude-haiku-4-5-20251001")
    return StubReplanLLM(
        seed=seed, variant_name=variant_name, target_location=target_location,
    )
```

**不做**：cost tracking / rate limiting / retry backoff —— 那是 model-budget。
第一版真 LLM 只是能跑即可。

### D6：replan_count 放 extensions 还是加字段

**选择**：extensions dict，键名 `replan_count`（int）+ `replan_by_day`
（list[int]，per-day 计数）。

**原因**：metrics spec 明文保留 `extensions` 给"未来 recorder 挂载"；避免
为观察一个 debug 指标就改 metrics typed 字段。

**实现**：`run_seed_with_metrics` 在每次 `memory.process_tick(...)` 返回的
`list[tuple[agent_id, trigger_event]]` 上累加；run 结束时：

```python
run_metrics = build_run_metrics(...)
run_metrics = run_metrics.with_extensions(
    replan_count=total_replans,
    replan_by_day=per_day_replan_counts,
)
```

### D7：行为差异的断言强度

**选择**：E2E 测试只要求**方向正确**：
```python
# hyperlocal_push 的 trajectory_deviation_m < global_distraction 的
assert hp_metric.trajectory_deviation_m < gd_metric.trajectory_deviation_m
```

**不要求**：
- CI 分离（3 天 × 2 seed 不够）
- 绝对数值（StubLLM 的路径不一定到达 target）
- baseline < hyperlocal_push（scripted plan 已经可能随机走到 target）

**原因**：本 change 目标是**因果链通**，不是**效应强**；强效应要等 30 seed
× 14 day 的 publishable suite 跑出来。

### D8：shared_anchor 的 target_location 怎么定

**问题**：SharedAnchorVariant 的 `task_templates` 提"在某堵墙上画了涂鸦"这种
描述——没绑具体 location。stub 如何知道把 agent 送到哪？

**选择**：shared_anchor 的 stub 行为 = "走向 Atlas 所有 outdoor_area 中
`area_type == 'park'` 或 `area_type == 'plaza'` 的第一个"（community 地点
heuristic）。若找不到 → 回退到 destinations[0]（与 hyperlocal_push 同 target）。

**承认 limitation**：这是粗糙的 dispatch；真 LLM 下会有更细的语义解析。
写进文档明示。

### D9：agent.should_replan 的触发阈值

**无需改动**：已有实现读 `profile.personality.routine_adherence` 与
`curiosity`，urgency > threshold 时触发。policy-hack 的 FeedItem 填了
`urgency=0.6`（hyperlocal）与 `urgency=0.4`（global_distraction）；默认人格
分布下会有约 30-50% 的 agent 被触发——够产生可观察差异。

## Risks / Trade-offs

**[Risk 1] StubReplanLLM 的 dispatch 表与 variants 不同步**
- variant 改名或新增时 stub 没更新 → stub 走 fallback 返 `[]` → 无行为
→ 缓解：测试覆盖每个 VARIANTS key，新 variant 若 stub 未更新则 test fail

**[Risk 2] shared_anchor 的 heuristic 选址不对**
- 选 park / plaza 可能在 Lane Cove OSM 里不存在类型
→ 缓解：fallback 到 destinations[0]；文档明示；不是方向不对就无所谓

**[Risk 3] real-LLM 路径跑崩**
- 真 Anthropic API key 没设 / 超额 / 404
→ 缓解：`--use-real-llm` 未设置时完全绕过；设置时加 try/except + 打印错误
  退出

**[Risk 4] Planner.replan 的 prompt 不含 origin_hack_id**
- D3 已经决定 stub 不依赖 prompt 内容——不是 risk

**[Risk 5] Memory.process_tick 性能**
- 每 tick 对所有 agent 调一次 should_replan ≈ O(agent × recent_events)
- 3 天 × 288 tick × 20 agent ≈ 17,000 次调用
- 已有 memory smoke（8/8 PASS）证明 100 agent × 288 tick 可跑；scale 上不怕
→ 缓解：无

**[Risk 6] StubReplanLLM 产出的 plan 与 runtime 不兼容**
- Planner.replan 的 parse 逻辑已有 fallback（JSON 失败返空 plan）
- stub 产 JSON 格式；需要与 `PlanStep` 字段对齐（time / action / destination /
  duration_minutes / reason / social_intent）
→ 缓解：测试覆盖 stub 产出被 Planner.replan 接受

## Migration Plan

1. 写 `tools/suite_stub_llm.py`
2. 修改 `tools/run_variant_suite.py`：
   - import + 构造 MemoryService / Planner / StubReplanLLM
   - 注册 memory hook
   - replan_count 采集
   - `--use-real-llm` flag
3. 写两个新测试文件
4. 文档
5. 6-variant × 2 seed × 3 天 smoke 跑，比较 hyperlocal_push 与
   global_distraction 的 trajectory_deviation_m —— 应不再相等
6. 更新 README

**回滚**：删 `tools/suite_stub_llm.py` + revert `run_variant_suite.py`；
其它不受影响。

## Open Questions

1. **Q1**: StubReplanLLM 是否该放进 `synthetic_socio_wind_tunnel/agent/` 供
   单元测试复用？
   倾向：不放——CLAUDE.md 明确 stub/demo 不进 package 路径；tests 本来就
   各自 mock
2. **Q2**: `--use-real-llm` 是否也跑 `memory.run_daily_summary` LLM？
   倾向：是——real-LLM 路径下让所有 LLM call 走同一 provider；stub 路径
   下 `run_daily_summary` 也用 stub（返回固定句子）
3. **Q3**: 是否需要额外的 Recorder 事件把 attention 触发的 replan 单独计入
   metrics？（目前 replan_count 是合计）
   倾向：本 change 不细分；未来想看 "per-variant replan 分布" 时单独加
