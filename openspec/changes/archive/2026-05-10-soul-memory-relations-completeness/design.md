## Context

`docs/agent_system/21-current-agent-design.md` §6-§7 列出 agent 灵魂 / 记忆 /
关系填充三件套。round-1 fix 把代码 ship 了但内容质量有大量缺口，2026-05-10
audit 揭示：

- **B1 archetype 实际匹配率 31.3%**（`python3 -c '...sample 1000 agents...'`），
  68.7% unmatched —— 7 个现有 archetype 完全没覆盖年轻 renter / mid-career
  renting families / older renters / casual workers
- **B2 life_history 是 LLM 凭空写**——没 archetype-specific Lane Cove 锚点
- **B3 social_priors 6 rules 在 1000 agent 上从未真跑过 audit**
- **B4 conversation_topics 完全未做**

本 change 一次性补完。

约束：
- 不破坏 1218 测试基线
- 不改 match_archetype 算法（合理）
- 不深度 Lane Cove 个体 web research（留 V2）
- archetype 扩展时保持 schema_version=1 兼容

## Goals / Non-Goals

**Goals**:

1. 1000 agent matched ≥ 80%（现状 31.3%）
2. 每个 archetype 有 ≥ 5 条 life_history 模板（archetype-grounded，不是
   pure-LLM）
3. social_priors 6 rules 在 1000 agent 上跑 audit，每 rule 至少产 1 条 tie
4. conversation_topics 注入到 do_something handler 的 prompt args

**Non-Goals**:

- 不改 match_archetype 算法
- 不深度 web research per-archetype 的真实居民故事
- 不重写 social_priors rules 内部逻辑
- 不动 spec capability 契约（B 是数据 / tool / 链路接口扩展）

## Decisions

### Decision 1：B1 加 4 个 fallback archetype

**Why**：68.7% unmatched 集中在 4 个 profile：
- 年轻 renter（< 28，commute/remote，renter，no kids）
- mid-career renting families（33-50，commute/remote，renter，kids）
- older renters（55+，retired，renter）
- casual / shift worker（任何年龄，shift work_mode）

加 4 个 archetype 覆盖这些，每个带 reasonable personality_bias + identity_text
template + interest pool。**接受不那么 Lane Cove-grounded**——填洞优先，深度
研究 V2。

### Decision 2：B2 life_history templates per-archetype

**Why**：LLM 凭空写的 life_history 任何城市看起来都一样。Lane Cove 风味来自
具体地名、学校、邻里事件。模板形式：

```json
{
  "longtime_owner_occupier": [
    "我 1992 年搬进 Lane Cove，那时这里还有不少 fibro 老房子",
    "孩子在 Greenwich Public 上的小学，现在已经搬出去自己住",
    "认识 Council 那位 Pam Palmer 二十多年了，她每次选都投",
    ...
  ],
  ...
}
```

`_generate_life_history_for_one` 改为：
1. 从 archetype 的 templates 里 sample N 条作为 anchor
2. LLM 在 anchor 基础上变奏（加具体年份 / 名字 / 细节）

### Decision 3：B3 audit script + 阈值微调

**Why**：6 rules 在数据上但未验证。简单审计 → 发现问题就调阈值，不重写 rule。

### Decision 4：B4 conversation_topics 直接 inject 到 prompt

**Why**：do_something handler 的 prompt 已经有 args 系统。新加一个 args 字段
`local_topics: tuple[str,...]`；prompt 增加一段 "Recent local discussion
topics: ..."，让 LLM 在生成 dialogue 时 reference。

## Risks / Trade-offs

- **[Risk]** B1 加的 4 个 fallback archetype 没深 research，有偏差风险 → Mitigation：
  在 archetype JSON 里 `uncertain: true` 标记，声明这是首版未深度校准
- **[Risk]** B2 模板可能太具体 / 太 generic → Mitigation：每 archetype 5-8 条，
  LLM 选 sample
- **[Risk]** B4 conversation_topics 5-10 条偏少，重复率高 → 接受首版，V2 扩展

## Migration Plan

1. B4（最小最独立）→ B3（audit only）→ B1（扩展数据）→ B2（template + 函数改）
2. 每步独立可测
3. 全量 regression ≥ 1218 passed
4. archive
