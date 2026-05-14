## Context

排查报告 `docs/audit/2026-05-09-bug-hunt.md` 给出的核心结论：当前 14-day publishable suite 的"thesis null 结果"主要由三条测量/装配链路 bug 制造，不是 thesis 真的失败：

- **B1**：`metrics::trajectory_deviation_m` 在 100 个 agent 上取 median，10 protag 信号被 90 scripted agent 稀释；
- **B2**：`StubReplanLLM` 给 `global_distraction` 返回 `<plan></plan>`，触发 Planner 退回 `deep_copy(unchanged)`，gd 的 44/57/105 次 replan 全是空 replan；
- **B3**：`PhoneFrictionVariant` 修改 `profile.digital`，但该字段在 movement 链路上无 reader（仅 perception filter / feed bias suppression 用），friction 在 scripted agent 上无任何可观测效应；
- **B4**：phone_friction 的 primary metric 选成 `attention.phone_feed_proxy`（pf 和 baseline 都不注入 feed → 都是 0）→ degenerate metric。

辅以 B5–B8 minor bug：traj_dev 对 gd 测错对象、Gemini cost 不记、replan_count 含空 replan、reproducibility_lock.phase_config 字符串索引污染。

约束：
- 不重写 hyperlocal_push（hp 已在工作，是 metric 测错对象不是 variant 失败）
- 不动 ai-town port / Gemini async client / dialogue pipeline（已稳定）
- 单元测试基线 1123 passed 必须维持
- variant 修复后必须有 contract test 验证"variant 真的产生了行为差异"，不能再次出现 inert variant

利益相关者：
- 后续 30-seed publishable change 的输入依赖；
- thesis 报告生成器（`tools/build_evidence_report_v3.py`）的 metric 字段消费；
- OpenSpec 已归档 changes（agent-stack-aitown-port / suite-wiring 等）的 spec 不能被破坏。

## Goals / Non-Goals

**Goals:**

1. `traj_dev_m` 改成 push-target subset median；同时输出 `traj_dev_m_all` 做 sanity 对照。
2. `phone_friction` 必须真制造 plan-level 行为差异（通过 attention_service 注入 friction-trigger event）；primary metric 换成 `encounter.per_day_median`。
3. `StubReplanLLM` 给 `global_distraction` 返回非空 plan（distraction step：去与 target_location 远离的方向 / 在原地多停留），让 stub 路径下 gd 也有可观测信号。
4. `replan_count` 拆成 `replan_count`（plan 真改）+ `replan_no_op_count`（空 replan），现有键保持向后兼容。
5. `reproducibility_lock.phase_config` 字符串索引 bug 修复。
6. 全套修复后 1 seed × 4 variant smoke 验证：
   - hp `traj_dev_m` < gd `traj_dev_m`（hp 把 target agent 拉过去；gd 没拉）
   - hp `encounter.per_day_median` < baseline；pf `encounter.per_day_median` > baseline（friction 让人回附近）
   - 4 variant 之间在 byte 层不再出现"全字段相等"

**Non-Goals:**

- 不改 hp 的 stub dispatch（hp 在工作）。
- 不重新设计 ai-town do_something / dialogue / reflection（稳定）。
- 不改 metrics 工厂的 encounter / weak_tie / space_activation / dialogue 计数算子（这些指标本身没 bug）。
- 不重跑 30-seed publishable run；本 change 只产 1 seed smoke 验证修复。
- 不动 fitness-audit / experimental-design spec。

## Decisions

### Decision 1：`traj_dev_m` 双口径（protag-only 主，all-agent 辅）

**Why**：thesis 信号在 push-target 子集上；all-agent median 在 90 scripted agent 主导下没有解释力。但保留 all-agent 作为 sanity 对照，能直接看出"hp 是只拉了 target 还是有 spillover"。

**How**：
```python
def _compute_trajectory_deviation_m(...) -> tuple[float|None, float|None]:
    target_ids = variant_metadata.get("target_agent_ids") or set()
    distances_target = []  # protag-only
    distances_all = []
    for agent_id, loc_id in end_locations.items():
        d = euclidean(loc_id, target_location)
        distances_all.append(d)
        if agent_id in target_ids:
            distances_target.append(d)
    return (
        statistics.median(distances_target) if distances_target else None,
        statistics.median(distances_all) if distances_all else None,
    )
```

`RunMetrics` 增加 `trajectory_deviation_m_all: float | None = None` 字段；老的 `trajectory_deviation_m` 字段语义改成 protag-only。

**备选**：一个字段 + 在 extensions 里塞 `trajectory_deviation_m_all`。否决：metric 升级路径不清晰，下游 reader 容易忘 fallback。

**风险**：现有 contest.json 与 build_evidence_report_v3 假设 `trajectory_deviation_m` 是全 agent median；语义切换会让历史数据不能直接对比。Mitigation：把语义变化写在 spec MODIFIED 里 + 在 docs/audit 里追加注释；老数据归档时已经写过 thesis 不靠 traj_dev 了，影响可控。

### Decision 2：`phone_friction` 通过注入 trigger event 制造行为差异

**Why**：B3 的根因是 friction 改的字段没有 movement reader。最干净的修法是用现有的 attention → memory → replan 通路：注入一个 `source="phone_friction_nudge"` 的 feed_item，被 attention service 投递成 trigger event，被 memory service 检测后触发 replan，让 planner 改 plan。这样 friction 就会通过 plan 层影响 movement，与 hp 走同一条因果链路（保持架构一致），只是触发源不同。

**How**：在 `apply_intervention_start` 之外新增 `apply_day_start` 注入逻辑：
```python
def apply_day_start(self, ctx: VariantContext) -> None:
    if ctx.attention_service is None:
        return
    target_ids = tuple(rt.profile.agent_id for rt in ctx.runtimes)
    item = FeedItem(
        feed_item_id=f"phone_friction_{ctx.seed}_{ctx.day_index}",
        content="今天注意力被屏幕拽走了——出去走走？",
        source="phone_friction_nudge",  # 新 source
        category="self_reflection",
        urgency=0.5,
        ...
    )
    ctx.attention_service.inject_feed_item(item, target_ids)
```

`StubReplanLLM` 在 `phone_friction` 的 dispatch 改成 `_plan_toward(community_heuristic_outdoor)`（户外公园 / 广场），符合"打破手机注意力，把人带回附近"的语义。

**备选**：直接在 plan 层做手术（删掉手机 step、替换成户外 step）。否决：变成"违反 architectural invariant 的 god-mode"——绕过 memory → replan 链路，破坏 variant pipeline 的可审计性。

**风险**：注入 feed_item 后所有 100 个 agent 都会触发 replan，pf 的 replan_count 会从 0 跳到 ~14×100=1400 量级，明显高于 hp 的 64–69。Mitigation：metric 阈值审计在测试里写"pf replan_count > 0 且与 hp 同数量级"，用 ratio 判而不是绝对值。

### Decision 3：`StubReplanLLM` 给 `global_distraction` 返回非空 distraction plan

**Why**：B2 的根因是 stub 给 gd 返回 `<plan></plan>` → Planner.replan 退回 `deep_copy(unchanged)` → gd 在 stub 路径下完全无效应。修复后 gd 必须有"global news 把 agent 注意力扯到无关方向"的可见效应——用一个固定的 "distraction destination"（一个非 hp target_location 的 outdoor area）作为 stub 目标。

**How**：
```python
elif variant_name == "global_distraction":
    distraction_dest = _pick_distraction_location(atlas, target_location)
    return _plan_toward(distraction_dest, rng=...)  # 走相反方向 / 远端 area
```

`_pick_distraction_location` 选规则：从 `atlas.list_outdoor_areas()` 中选一个**距离 target_location 最远**的 area（保证可观测的方向相反）。若 atlas=None，fallback `destinations[-1]`。

**备选**：返回"在原地多停留"的 step（duration=120 分钟）。否决：在 scripted_plan 上叠加 stay 后下一个 step 自然继续，行为差异太小、与 baseline 难以拉开。

**风险**：选 farthest area 在 Lane Cove 这种地图上可能选到 hp 真没用上的某个固定角落；多 seed 跑下来 gd 的 traj_dev 会非常稳定（IQR 窄）。这是可接受的——stub 本来就是 deterministic dispatch。Mitigation：spec 里写 stub 的目的是"操作语义工作"，不是"模拟真实 LLM 的方差"。

### Decision 4：`replan_count` 双计数

**Why**：B7 让 metric reader 误解 gd 改了 plan。修法是在 `memory.process_tick` 比对 `new_future_steps` 是否真非空，分别 +1 到两个 counter；保留 `replan_count` 名字含义为"plan 真改"，新增 `replan_no_op_count` 表示"调用了 LLM 但 plan 没变"。

**How**：`Planner.replan` 已经在 fallback 时返回 `deep_copy(unchanged)`。memory.service 的 hook 不知道哪种是 fallback。最干净修法：让 `Planner.replan` 返回 `tuple[DailyPlan, bool]`（plan, changed）；memory 据此分流计数。或者：让 `Planner.replan` 在 fallback 时 raise `ReplanNoOp` exception，memory 捕获后计入 no_op counter。

选 tuple 方案——breaking 但更显式，比 exception 流更易测试。

**备选**：在 plan 上加 `last_replan_changed: bool` 标志。否决：state 蔓延到 model，与 frozen Pydantic 不兼容。

**风险**：Planner.replan 的 caller 都要改。grep 看下游就 memory.service 一处，可以一次性改完。

### Decision 5：`reproducibility_lock.phase_config` 修字符串索引

**Why**：B8 显然 bug，无设计决策。

**How**：在调 `compute_reproducibility_lock` 前 `parts = [int(x) for x in args.phase_days.split(",")]`，传 `parts[0]/[1]/[2]`。

## Risks / Trade-offs

- **[Risk]** B1 修复后 hp 的 `traj_dev_m`（protag-only）会突然从 ~325 变到一个完全不同的量级（可能更大，因为没了 scripted agent 拉低 median）→ Mitigation：在 spec 写明 metric 语义切换；`build_evidence_report_v3` 模板里同时显示 protag-only 与 all 双值。
- **[Risk]** B3 修复让 friction 把所有 100 agent 都触发 replan，cost 也会上升（如果 `--use-real-llm`）→ Mitigation：smoke 用 stub；30 seed publishable 跑前评估 cost；可加 `friction_target_ratio` 字段仅注入给一部分 agent。
- **[Risk]** B2 修复后 gd 在 stub 路径下变得 "always pulls toward distraction_destination"，paired mirror 的 `mirror_delta` 不再 = 0；老的 contest.json 阈值假设需更新→ Mitigation：spec MODIFIED 里写明 mirror_delta 含义切换。
- **[Trade-off]** Decision 4 改 `Planner.replan` 返回 tuple → 影响所有现有 caller。grep 确认只有 1 处，影响可控；如未来有新 caller 必须更新。
- **[Trade-off]** 不引入新 capability，只 MODIFY 三个现有 spec → 保持归档边界清楚，但 spec MODIFIED 内容偏多；archive 时要小心 full-content 复制规则。

## Migration Plan

1. 先改 specs（三个 MODIFIED delta）+ design 通过 review。
2. 实施 Decision 5（B8 phase_config）—— 最小、独立、零回归风险，先合。
3. 实施 Decision 1 + 4（metrics + replan 双计数）—— 修改 metrics/factory 与 metrics/models；同时改 build_evidence_report_v3 的 reader。
4. 实施 Decision 3（gd stub）+ Decision 2（pf trigger event）—— 与 spec 保持同步。
5. 跑 1 seed × 4 variant smoke：
   - 验证 hp.traj_dev_m (protag-only) < gd.traj_dev_m (protag-only)
   - 验证 pf.encounter.per_day_median > baseline.encounter.per_day_median
   - 验证 4 variant 在 encounter / replan / weak_tie 上不再出现"全字段 byte-identical"
6. 走通后 commit；下一个 change（30 seed publishable）单独开。

回滚策略：每个 Decision 单独 commit；若 smoke 异常，回滚到最近一个 green commit。

## Open Questions

1. `phone_friction` 的 trigger 注入是否要 protag-only？还是全员？— 默认全员（pf 是 attention-main 的全民操作）；若 review 说 protag-only 更对应实验设计，再加 `friction_target_ratio` 字段。
2. `traj_dev_m` 的 protag-only subset：用 `is_protagonist` 标记还是 variant 自己的 `target_agent_ids`？— 用 `variant_metadata.get("target_agent_ids")`；若缺省（pf / baseline）退回 None；hp/gd 在 variant 注入时已经把 target_agent_ids 写到 metadata。
3. 是否要在本 change 里也改 contest.json 的 `phone_feed_proxy` → `encounter.per_day_median`？— 是。和 Decision 2 同步改 metric mapping，不然 pf 的 primary metric 仍是退化的 0。
