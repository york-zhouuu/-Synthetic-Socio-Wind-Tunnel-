## Context

`docs/agent_system/20-realism-roadmap.md` Stage 4 + B3 audit (2026-05-10) 都点
出当前 sample_population 给每个 agent 独立 home_location（home_0000 /
home_0001 / ...），导致：

- household_kin social_prior rule 0 ties
- baseline encounter density 缺 family-driven co-presence
- 同 household agent 行为完全独立 —— 不真实

约束：
- 不破坏 1238 测试基线
- AgentProfile 是 frozen Pydantic，新字段必须有合理默认值
- 不重写 LifePattern / Plan / Atlas / Ledger

## Goals / Non-Goals

**Goals**:

1. household_id 在 AgentProfile 上立起来，sample_population 按 household 单元
   采样
2. 同 household agent 共享 home_location_id
3. household_kin social_prior rule 至少产 50 ties on 1000 agent
4. scripted_plan 加 morning drop-off + weekend co-trip 两个联动点
5. baseline encounter density 上升 5-15%（真跑后看）

**Non-Goals**:

- 不实现完整家庭日历同步
- 不重写 LifePattern
- 不动 ai-town 决策树（protag 仍按个体决策）

## Decisions

### Decision 1: 用 household_id 而不是 household 复合 key

**Why**: 单一 unique id 让 SocialGraphService.preload_ties 直接 group-by；
比组合 (home_location, family_composition) 更稳。

### Decision 2: sample_population 先采 household 再展开成员

**Why**: 反序更自然 — 先决定"有多少 households 各种类型"再分发 agent。

### Decision 3: scripted_plan 读 household_context 做 weak coordination

**Why**: 强联动（每分钟同步）会让 plan 生成复杂 5x；只做 2-3 个联动点（morning
drop-off / weekend co-trip）能拿到 80% realism gain，10% 复杂度成本。

## Risks / Trade-offs

- [Risk] household_id sampling 改了 LANE_COVE_PROFILE 默认行为 → 现有测试
  断言 home_location 唯一性的会破 → Mitigation: grep 现有 tests，逐一审。
- [Risk] morning drop-off 增加 7-9am 的 encounter peak，可能让 realism test
  阈值再次需要校准 → Mitigation: smoke 后看。

## Migration Plan

1. AgentProfile 加字段（默认值兼容）
2. HouseholdRegistry + sample_population 改采样逻辑
3. scripted_plan 读 household_context
4. smoke 验证 + tests
5. archive

## Open Questions

1. weekend co-trip 概率 30% 是否合理？—— 凭直觉；smoke 后看
2. morning drop-off 时间窗 ±15min？—— 可调
