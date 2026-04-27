## Context

`agent-calibration` (2026-04-27) 把 6 维 ABS Census 接进 sim，best-effort 5/6
通过。但 ABS DataPack 还有大量 thesis-direct 字段未挖：照护时长、社区资历、
志愿身份、英语熟练度、家庭组成等。

本 change 的核心动机：让 sim 能区分 *rooted* vs *floating* agent，从而支持
"hyperlocal push 在不同人群上效果不同"的 rival hypothesis。这是 attention-
induced nearby blindness 的下一层切片。

## Goals / Non-Goals

**Goals**：
- AgentProfile 增 13 个 thesis-direct 字段
- LANE_COVE_PROFILE 的所有新字段从 ABS DataPack 派生
- 新字段全 Optional，向后兼容
- calibration 自动覆盖（best-effort 阈值递进式）
- 不破任何现有测试

**Non-Goals**：
- 不让 LLM Planner 当下就用所有 13 字段（prompt 信息过载留给后续 change）
- 不实现"基于 care_hours 的差异化 hyperlocal push 推送"（属 policy-hack 的
  下游 change）
- 不做 ABS Religion / Health / Industry / Occupation（thesis 关联弱）
- 不破 Household 字段（保留作 alias，避免 cascading test 修改）

## Decisions

### D1：13 字段全 `Literal | None = None`

**选择**：所有新字段类型 `Literal[...] | None`，default `None`。

**Rationale**：
- 向后兼容硬要求——存量 AgentProfile 构造代码不传新字段也工作
- Literal 类型给 LLM downstream（prompt template）提供确定词表，减少自由
  发挥导致的 stereotype noise（参考 lightweight-llm-format 的 dispatch 词表
  原则）
- `None` 默认 = "未模型化"，与 calibration 的 missing-data 状态对齐
  （部分维度可能下个数据更新才补）

### D2：Family composition 替代 Household（不破契约）

**选择**：
- 新增 `family_composition: Literal[7-bucket] | None`
- 保留 `household: Household = Literal["single", "couple", "family_with_kids"]`
  当前签名（默认值由 family_composition 推断）
- sample_population 优先从 family_composition_distribution 采样，再回填
  household 三桶

**Rationale**：
- 降级映射规则：
  - `lone_person` → single
  - `couple_no_kids` / `couple_kids_15plus` → couple
  - `couple_kids_under_15` / `one_parent_family` → family_with_kids
  - `group_household` / `other` → single（fallback）
- 让既有依赖 `agent.household` 的代码（test fixture / scripted_plan branching）
  继续工作；新代码用更细的 family_composition

### D3：用 5-year residence 而非 1-year（G45 不 G44）

**选择**：community_tenure_5yr，3 桶（new <1yr / recent 1-5yr / established 5plus）。

**Rationale**：
- 5 年是社区 ties 形成的更稳定窗口（1 年太短，刚搬来的人都还没建立社交）
- G44（1-year）数据有但更 noisy（包括短期租约切换、内部小搬）
- 3 桶足够支撑 thesis rival hypothesis；不需要更细

### D4：照护时长用 ABS 桶（不 normalize 为连续 hours）

**选择**：unpaid_*_hours 字段都是 Literal["none", "1_14", "15_29", "30plus"]。

**Rationale**：
- ABS G24/G25/G26 直接给桶；"normalize 到连续 hours"会引入虚假精度
- LLM prompt 处理桶（"轻度家务负担"）比处理"每周 9.7 小时"更自然
- 校准 chi² 用桶天然适配

### D5：English Proficiency 5 桶（含 english_only）

**选择**：`Literal["very_well", "well", "not_well", "not_at_all", "english_only"]`。

**Rationale**：
- ABS G13 给非 English-only 人群的 4 档 proficiency
- 加一档 "english_only"（家中只说英语）= 完整覆盖
- thesis 用途：non-English 家中说话 + proficiency 低 = "**双重文化隔离**"agent；
  对 hyperlocal push（多用英语）反应弱

### D6：volunteer_status 二元（不细分组织类型）

**选择**：Literal["volunteer", "non_volunteer"]。

**Rationale**：
- ABS G23 只区分志愿 / 不志愿（不分志愿组织类型）
- 二元就够 thesis：volunteer = 已有 weak-tie network → hyperlocal push 边际
  收益低
- 想要"哪类组织志愿"得用 G56（Industry of Volunteer 的 organization）—— 后续

### D7：disability_status 用 G18 不 G19

**选择**：`disability_status: Literal["needs_assistance", "no_assistance"] | None`（G18）。

**Rationale**：
- G18 (Core Activity Need for Assistance) 是 ABS 标准残障定义；G19 是医疗
  类型分布（与 thesis 弱相关）
- needs_assistance = 需要日常协助 = 高度 anchored to local services
- 1-bit 信号；够用

### D8：calibration 评估递进式

**选择**：

```python
# Tier 1 dims (existing 6 + 5 new core thesis dims): need 4 of 6 + 3 of 5
# Tier 2 dims (5 refinement): bonus, no failure
# Tier 3 dims (3 completeness): bonus, no failure
```

具体规则：
- best-effort: 现有 6 维 ≥ 4 通过 **AND** 新 Tier 1 5 维 ≥ 3 通过
- strict: 现有 6 维全过 **AND** 新 Tier 1 全过 **AND** Tier 2 ≥ 3 通过

Tier 3（indigenous / disability / education）不阻塞 archive；它们的状态出
现在 disclosure 段。

### D9：convert_abs_census.py `--full` flag

**选择**：CLI 加 flag：
- 不带：当前行为（6 维）
- `--full`：13 维全输出

**Rationale**：
- 不破现有调用（agent-calibration 的 6 维 JSON 不变 by default）
- archive 时 user 跑 `--full` 一次更新 JSON
- 方便回滚：取消 `--full` 即可生成只有 6 维的旧 JSON

## Risks / Trade-offs

**[Risk 1] 13 字段 sample_population 慢**
→ `_weighted_pick` 每个 ~50ns；13 × 1000 agent = 650 µs total。可忽略。

**[Risk 2] Pydantic Literal 验证失败 on 老 fixture**
→ 新字段全 Optional default None；老代码不传不报错

**[Risk 3] family_composition 与 household 不一致 bug**
→ sample_population 内部强制保持映射规则（D2）；加单元测试

**[Risk 4] ABS 数据某些维度对应 SA2 桶过细 / 过粗**
→ 我们桶是从 ABS 桶简化的；converter 内部做 ABS bucket → our bucket 映射；
  在 docs/calibration/01-data-sources.md 详细记录每个映射

**[Risk 5] new fields 让 stereotype audit 更容易"中"**
→ stereotype audit 是 future change；本 change 不实施 audit。如果 13 维并入
  让 audit 检测出"高 care_hours agent 被 LLM stereotyped 为 caring/nurturing"
  —— 那是 audit 的 finding，不是 bug

**[Risk 6] 数据量太大 LLM prompt 引用全字段失控**
→ 本 change **不**改 Planner prompt（D Non-goal）；新字段先存而不引

**[Risk 7] Calibration acceptance 阈值过宽 / 过严**
→ D8 阈值刻意分层：核心 6 维不能倒退 + 新 5 维 ≥ 3/5；其余字段是"加分项"

## Migration Plan

阶段 1（schema, 0.5 day）：
1. profile.py 加 Literal 类型 + 13 字段
2. population.py 加 PopulationProfile distribution 字段（默认值）
3. household ↔ family_composition 映射逻辑

阶段 2（converter, 1 day）：
4. convert_abs_census.py 加 13 个 extractor
5. `--full` flag
6. 跑一次 → 更新 abs_census_lanecove_2021.json

阶段 3（profile values, 0.5 day）：
7. LANE_COVE_PROFILE 加 13 个 distribution（从 JSON 读 / hardcode）
8. sample_population 采样新字段
9. household 自动从 family_composition 推断

阶段 4（calibration, 0.5 day）：
10. calibration.py 自动评估新维度
11. assess_population_calibration 阈值递进逻辑
12. run_calibration.py 输出按 Tier 分组

阶段 5（测试, 1 day）：
13. test_agent_population 扩展
14. test_calibration 扩展
15. test_profile_enrich_thesis_dims 新建
16. 修复连带破坏的现有测试

阶段 6（docs + verify, 0.5 day）：
17. 更新 01-data-sources.md（13 张表 + 桶映射规则）
18. 跑 calibration → 报告新 13 维通过率
19. 全 pytest 通过
20. validate --strict

**回滚**：`git revert` + 删 JSON 新字段

## Open Questions

1. **Q1**：household 字段最终保留还是去掉？
   倾向：保留作 alias，等下个 change `agent-profile-cleanup` 再去掉。本 change
   只新增不删除。

2. **Q2**：volunteer_status 是否应该和 weak-tie network 直接挂钩（影响 sim
   social interaction）？
   倾向：本 change 只存字段；行为 hook 留给 social-graph capability 后续
   change。

3. **Q3**：non_binary gender 在 ABS 数据缺失，新字段（如 indigenous_status）
   是否也允许 distribution 含 0-weight 桶？
   倾向：是。Pydantic validator 已支持（用 dict 不全列举即可）。

4. **Q4**：community_tenure_5yr 与 migration_tenure_years 概念重叠（前者是
   community 维度，后者是 country 维度）—— 是否要合并？
   倾向：不合并。Community tenure（在 Lane Cove 待多久）≠ migration tenure
   （来澳多久）。在 Sydney 内部搬迁的 agent 可能 migration_tenure_years=null
   但 community_tenure_5yr=new。两个维度独立有用。

5. **Q5**：LLM prompt 何时开始用新字段？
   倾向：本 change 不动 prompt。下个 change `agent-prompt-enrich`（独立小
   change）评估"哪几个字段加进 prompt 不会让 LLM 输出退化"，按维度逐个 a/b
   测试。
