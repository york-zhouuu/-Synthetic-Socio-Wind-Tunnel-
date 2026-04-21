## Context

Phase 1 基建完成后，进一步的直觉检查暴露了五个漂移点（详见 `proposal.md`）：
侦探引擎血统残留、数字注意力层缺失、profile 社会结构贫血、场地与 thesis 错位、
风洞可信度无锚。本 change 不是要"重写 Phase 1"，而是在 Phase 2 大规模动工前
先做**一次审计 + 最小适配**，把剧组模型变成"适合跑社会实验的剧组模型"。

当前代码库的契约形状：
- 10 个已冻结 capability（`openspec/specs/*/spec.md`）
- 1 个 Phase 2 roadmap（尚未开工）
- Lane Cove atlas 已工程化落地（3800+ buildings，主连通分量 ≥85%）
- AgentRuntime + Planner 已有 Phase 1 实现；一日一次 LLM 生成计划

这意味着审计 **必须跑在真实 Lane Cove atlas 上**（而非 toy fixture），并且
不能依赖 Phase 2 的 orchestrator（orchestrator 还没有）。审计代码自己要能
"最小驱动"——手工推进几步 tick、手工调用 simulation 方法——来测基建。

## Goals / Non-Goals

**Goals:**
- 让"基建能否承载 thesis"这个**主观判断**变成**可执行的 pass/fail**；
- 给 Phase 2 的每块 capability 一个**证据锚点**（哪条审计失败 → 哪块必须建）；
- 把数字注意力从 Policy Hack 的一个分支机制 **提升为一级接口**，让 Phase 2 的
  `policy-hack` / `conversation` / `perception` 能复用同一套通道；
- 给 AgentProfile 补齐社会结构维度，使 1000 人群采样能复现 thesis 所需的异质性；
- 为 Phase 2 的 `metrics` change 提前锁定最小观测原料（trajectory 导出、
  feed 曝光日志）。

**Non-Goals:**
- 不在本 change 中实现 Phase 2 的 7 块能力；
- 不重写 CollapseService / 不删除 EvidenceBlueprint / 不改已冻结 spec 的任何
  Requirement 措辞（除非 MODIFIED 合规）；
- 不切换数据场地（Lane Cove → Zetland）；
- 不做可视化前端或叙事质量评估；
- 不引入新第三方依赖。

## Decisions

### D1: `fitness-audit` 作为一级 capability（而非纯 pytest 用例）

**决定**：新建一个 `synthetic_socio_wind_tunnel/fitness/` 模块与对应 spec，
审计结果序列化为结构化 `fitness-report.json`。

**备选**：把审计写成若干 `tests/test_integration_*.py`，不入 spec。

**为什么选前者**：
- OpenSpec 契约驱动，审计结果需要在 change archive 时被验证（"所有 `pass` 的
  测试 PASS"作为前置门禁）。pytest 是运行机制，不是契约。
- 审计会被 Phase 2 的每块 change 引用（作为"我必须解决哪条 fail"的证据）。
  让它成为一级 capability 才能在 spec 层被引用。
- 未来 Phase 3 的真实场地接入（例如 Zetland）也要跑同一套审计；
  把它变成 capability 就能"对新场地重跑一遍"。

### D2: `attention-channel` 独立 capability，不是 perception 扩展

**决定**：新建 `synthetic_socio_wind_tunnel/attention/` 模块，`FeedItem` /
`NotificationEvent` / `AttentionState` / `DigitalProfile` 活在这里；
perception 通过一个 filter 消费。

**备选**：把 FeedItem 等塞进 `perception.models`，通道就是感知的一种。

**为什么选前者**：
- 数字通道有**独立状态**：feed history、notification queue、算法偏向参数，
  这些不属于"瞬时感知"，属于"跨 tick 的 agent 状态"。Ledger 里归一张新表。
- 通道是**多写多读**：agent 读；policy-hack 写；metrics 读；social-graph
  未来可能读（"信息扩散"）。perception 只是消费端之一。
- 与 `WorldEvent` / `AgentKnowledgeMap` 的关系清晰：digital 通道的事件
  继承 `WorldEvent(event_type=NOTIFICATION_RECEIVED)`，但**不**经过物理
  `audible_range` / `visible_range`——另一套传播规则。

### D3: DigitalProfile 的社会学边界：可观察事实，不评分

**决定**：DigitalProfile 只记可观察字段：
`daily_screen_hours: float`、`feed_bias: Literal["global", "local", "mixed"]`、
`headphones_hours: float`、`notification_responsiveness: float (0-1)`。

**不含**："媒体素养评分"、"信息茧房程度"、"孤独指数"等主观合成指标。

**为什么**：与 `atlas.affordance` "不做数值打分"的既有规则对齐；合成指标
交给 agent 自己的 LLM 从 profile 推理得出，避免我们把"假设的因果"偷偷变成
"基建的给定"。

### D4: 族裔 / 收入等敏感字段的处理

**决定**：
- 所有敏感字段在 `AgentProfile` 上可为 `None`；
- `agent.population` 采样模块使用"群组画像"（demographic mix）生成，
  不在 profile 层硬编码族裔名称的语义；
- `ethnicity_group` 用**区域码**（`AU-born`, `AU-migrant-1gen`,
  `AU-migrant-2gen-asia`, `AU-migrant-2gen-europe`, ...）而不是具体国籍，
  避免冒犯性细分；
- profile 生成的 seed 被 metrics 记录，任何基于族裔的聚合结论必须在
  `fitness-report.json` 中可追溯。

**为什么**：thesis 本身涉及社会结构异质，缺这些字段就无法建模现象；
但必须避免把 LLM 的"族裔刻板印象"引入 profile。可观察的结构 + LLM 的自由解读
是两条线。

### D5: 场地锚定 Lane Cove

**决定**：Lane Cove 是最终场地。审计只跑 Lane Cove atlas，site-fitness 条目
不做"与其它场地对照"，只做 Lane Cove 自身的数据陈述（named / residential /
density）。

**为什么**：
- Lane Cove atlas 已工程化，工具链、富化管线、连通度门禁都就位；
- 用户确认放弃 Zetland 设想，避免再保留占位 preset 与对比阈值；
- 保留"场地任意"作为 cartography capability 的既有语义——`GeoJSONImporter`
  对任何 bbox 都工作；换场地时开独立 change，不是在本 change 中保留"什么
  都能跑"的幻觉。

### D6: CollapseService 不改，但**标注路径**

**决定**：不修改 `collapse` spec 的任何 Requirement。但在
`fitness-audit` spec 中声明 "`collapse` 不属于 measurement-critical path"，
审计不测 CollapseService 的行为。

**为什么**：EvidenceBlueprint / DirectorContext 是 narrative 实验（Act IV
Stories）需要的；删掉会打断叙事输出。保留 + 文档化为"可选路径"，成本低于
删除与迁移。

### D7: 审计报告的 schema

`fitness-report.json` 的顶层：

```json
{
  "schema_version": "1.0",
  "generated_at": "<ISO8601>",
  "atlas_source": "data/lanecove_atlas.json",
  "atlas_signature": "<sha256 of atlas.json>",
  "categories": [
    {
      "category": "e1-digital-lure",
      "results": [
        {"id": "e1.push-reaches-target", "status": "pass|fail|skip", "detail": "..."},
        ...
      ]
    },
    ...
  ],
  "scale_baseline": {
    "agents": 1000,
    "ticks": 288,
    "wall_seconds_p50": <float>,
    "wall_seconds_p99": <float>
  },
  "cost_baseline": {...},
  "site_fitness": {
    "named_building_ratio": <float>,
    "residential_ratio": <float>,
    "zetland_gap_notes": "..."
  }
}
```

每条 `status: "fail"` SHALL 附 `mitigation_change` 字段，指向应由哪个
Phase 2 change 修复（可能是尚未创建的，这样就给 Phase 2 的 proposal 一个
强制入口点）。

### D8: 不引入 orchestrator 的审计如何驱动 tick

审计代码自己造一个极简的 `_MinimalTickDriver`，放在
`synthetic_socio_wind_tunnel/fitness/driver.py`：手工 `advance_time` +
手工调用 `simulation.move_entity` + 手工触发 `pipeline.render`。
不写入 orchestrator capability，也不与之重叠——orchestrator 会做真正的
并发调度、冲突裁决、路径相遇检测，`_MinimalTickDriver` 只做"最小推进"
以验证基建 API 可用。

## Risks / Trade-offs

**[R1] 审计"假阴性"** → Mitigation：每条 audit 的 `detail` 写"what 失败
与 how 复现"；`tools/run_fitness_audit.py --category e1 --verbose` 能
打印单条的完整上下文。

**[R2] DigitalProfile 出现"伦理争议字段"** → Mitigation：D3 + D4 的
保守字段集；IRB 风格的字段申报在 design.md（本文件）与 CLAUDE.md
双份记录；profile 采样种子可复现。

**[R3] attention-channel 与未来 Phase 2 `policy-hack` 的接口冲突**
→ Mitigation：本 change 只定义 `NotificationEvent` 与 `feed_ingest` 的
**数据形状**，不定义"谁来触发"；`policy-hack` change 会写 trigger 逻辑。
两者的边界在 design.md 里显式画出。

**[R4] 审计"自我合理化"（套娃）**：本 change 既新建了 attention-channel /
population 等能力，又写了对应审计条目。如果不区分，审计对 Phase 1 裸代码的
适配度测量就失真。
→ Mitigation：审计拆成三类 category——`phase1-baseline` / `phase2-gaps`
做存在性探针（对裸 Phase 1 会 FAIL；mitigation 指向补齐的 change），
`e1/e2/e3/profile/ledger` 做集成测试（假设能力已存在），`site/scale/cost`
做纯数据诊断。这样"Phase 2 每块 change 引用一条 fail 条目"有了真正的
锚点，而不是空承诺。

**[R5] 1000 agent × 288 tick 在 CI 上太慢** → Mitigation：审计默认跑
"`scale_baseline`=100 agent × 72 tick"，完整 1000×288 仅在 `--full` flag
下跑；CI 只跑 quick 版，完整版在本地 / nightly。

**[R6] DigitalProfile 默认值会污染 Phase 1 已有测试**
→ Mitigation：所有新字段默认 `None` 或 0.0 且不参与现有测试断言；
现有 `AgentProfile(...)` 构造调用无需修改。

## Migration Plan

1. 创建 `synthetic_socio_wind_tunnel/fitness/`、
   `synthetic_socio_wind_tunnel/attention/` 目录
2. 扩展 `AgentProfile`（向后兼容：默认 `None`）
3. 给 `ObserverContext` 加 `digital_state: AttentionState | None = None` 字段
4. 在 `perception/filters/` 加 `digital_attention.py`，默认**不加入管线**
   （需要显式启用）
5. 写 `_MinimalTickDriver` + 审计套件
6. `tools/run_fitness_audit.py` 产出 `data/fitness-report.json`
7. 更新 `__init__.py` re-export
8. 在 `openspec/changes/phase-2-roadmap/tasks.md` 中加一条前置条件：
   "每块 Phase 2 change 开工前，引用 `fitness-report.json` 中对应的
   `fail` 条目作为其动机"

### 回滚
- 新增模块默认不加入已有 pipeline；删除新目录 + 撤回 `__init__.py`
  re-export 即可完全回退，Phase 1 行为不受影响。

## Open Questions

- **Q1**：审计覆盖"规模基线 1000×288"是否足够？如果 Phase 2 要模拟 30 天，
  是否需要扩展 baseline？
  → 建议：本 change 只做单日；多日在 `orchestrator` change 里独立审计。
- **Q2**：`DigitalProfile.feed_bias` 仅有 "global / local / mixed" 三档是否
  太粗？
  → 建议：先粗，等 Experiment 1 首轮运行后有数据再细化。
- **Q3**：是否需要在 `fitness-report.json` 中加"可复现种子"块？
  → 是。加 `seeds: {profile, population, atlas_hash}`。
- **Q4**：现在的 `EventType.NOTIFICATION_RECEIVED` 等是否应归 core/events，
  还是 attention-channel 自身？
  → 归 core/events（与 SOUND_* 同级），保持事件为 cross-cutting；
  attention-channel 只定义**数据模型**与**工厂**，事件类型在 core。
