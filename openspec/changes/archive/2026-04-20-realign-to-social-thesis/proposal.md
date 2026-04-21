## Why

Phase 1 交付的空间引擎在血统上更接近"LLM 驱动的侦探推理游戏"，而项目 Brief 的 thesis
是 **"数字注意力在高密度社区中制造隐形社会边界"**。两者在以下位置发生偏移，
必须在 Phase 2（orchestrator / memory / metrics）启动前先审计并适配——否则将在
错误的基建上造正确的特性：

1. **数字注意力层缺失**：thesis 的核心变量是"手机 / 推流 / 注意力位移"，但
   `ObserverContext` 只有视觉 / 听觉 / 嗅觉 / 技能 / 情绪滤镜，没有任何
   "正在刷手机 / 本地推送是否被看到 / 算法偏向"这类的机制。`Policy Hack` 的
   `info_injection` 在 Phase 2 roadmap 中被粗略描述为"写入 agent 感知"，
   绕开了 thesis 的核心机制。
2. **侦探引擎血统的残留**：`CollapseService` 的 `DirectorContext` 举例是
   "带血的物品 / 隐藏的信件 / 凶手 / Emma 发现关键证据"；`EvidenceBlueprint`
   以"剧情必需证据"为核心；`ItemState` 有 `is_hidden / discovery_skill`。
   这些在社会实验路径上不会被触发，但占据认知与接口表面。
3. **AgentProfile 的社会结构贫血**：只有 OCEAN-ish `personality_traits`、
   `interests`、`languages`、`household`。缺失族裔 / 租期 / 移民年限 /
   收入层 / 工作模式——这些恰恰是悉尼高密度社区边界的主轴。以现有 profile
   生成的 1000 agent 会**人格异质 + 结构同质**，无法复现 thesis 的现象。
4. **场地已经确定为 Lane Cove 2066**：此前 Brief 文本来自 Zetland/Green Square
   的现象观察，但真实落地的底板与 atlas 是 Lane Cove。本 change 顺势把场地
   决策冻结下来：thesis 的适用性以 Lane Cove 为准，不再保留其它场地的
   hypothesis 占位；后续 change 想换场地的话 SHALL 开独立 change 并说明
   数据来源。
5. **风洞可信度无锚**：没有任何外部 ground truth（empirical fit / 理论复现 /
   before-after real-world）。Experiment 1 的产出是"LLM 基线 vs LLM 干预后"，
   用 LLM 叙事说明——如果不先给"什么叫做风洞有用"下定义，跑完也无法答辩。

上述五条叠加，意味着**在 Phase 2 前，应该先跑一个"适配 + 验证"的 change**，
证明（或证伪）Phase 1 基建能承载 thesis。本 change 做这件事。

## What Changes

### 1. 引入"适配度审计"作为一级能力（NEW）

新增 `fitness-audit` 能力：一套可执行的 acceptance test 与诊断脚本，
对 Phase 1 基建逐条验证是否能支撑三个实验。审计分三类条目，避免"自我
验证套娃"：

- **基线存在性条目**（`phase1-baseline.*` / `phase2-gaps.*`）：检查某块
  能力**是否存在**（通过 import 与关键 API 探针）。对 Phase 1 裸代码跑
  应该 FAIL，指向对应 change；对当前代码跑能反映真实集成进度。
- **集成条目**（`e1.* / e2.* / e3.* / profile.* / ledger.*`）：在能力已存在
  的前提下，测端到端集成。失败指向集成 bug 而非缺能力。
- **诊断条目**（`site-fitness / scale-baseline / cost-baseline`）：纯数据
  快照，不 gate、不做 judgemental 对比（场地已锚定 Lane Cove）。

审计 SHALL 产出一份 `fitness-report.json`，每条测试带
`pass/fail/skip + mitigation_change`。**Phase 2 每块 change 的 `## Why`
SHALL 引用一条 `mitigation_change` 指向该能力的 AuditResult**（基线条目
提供锚点，不要求 Phase 2 change 与"fix"一一对应）。

### 2. 引入"数字注意力通道"能力（NEW）

新增 `attention-channel` 能力：把 thesis 的核心变量提升为一级机制，而不是
藏在 Policy Hack 的 "info_injection" 分支里。至少包含：

- `FeedItem`（手机上的一条内容：global / hyperlocal / commercial）
- `NotificationEvent`（推送事件，附 source、urgency、hyperlocal_radius）
- `AttentionState`（agent 当前的注意力分配：physical_world / phone_feed / task）
- `DigitalProfile`（AgentProfile 的子字段：screen_time_hour、feed_algorithm_bias、
  headphones_usage_hour 等）

并通过一个**新 perception filter**（`digital_attention`）决定：当 agent 处于
"低头看手机"状态时，物理 SubjectiveView 的 notable observation 被削减；
反之，push 的 hyperlocal 内容进入感知流。

### 3. 修订 `agent` 能力：补齐社会结构维度（MODIFIED）

`AgentProfile` 新增一组**结构性**字段（独立于现有人格维度）：

- `ethnicity_group: str`（自由文本 / 区域码，不做价值判断）
- `migration_tenure_years: float | None`
- `housing_tenure: Literal["owner_occupier", "renter", "public_housing"]`
- `income_tier: Literal["low", "mid", "high"]`
- `work_mode: Literal["commute", "remote", "shift", "nonworking"]`
- `digital: DigitalProfile`（见 `attention-channel`）

这些字段 SHALL 与 `personality_traits` 正交；**生成 1000 人群时的联合分布**由
`agent.population` 子模块负责，应能从配置的"社区人口画像"采样而非手工指定。

### 4. 修订 `perception` 能力：增加 digital_attention filter（MODIFIED）

`PerceptionPipeline` 的 filter 链 SHALL 支持 `digital_attention` 插槽，
位于物理 filter 之后、叙事渲染之前；它读取 `observer_context.digital_state`
并：

- 若 agent 当前 `attention_target == phone_feed`，则 `SubjectiveView.observations`
  中物理源的 `is_notable=True` 项 SHALL 按注意力比例下降
- 若 `observer_context.notifications` 非空，SHALL 生成一组 `Observation(sense=DIGITAL)`
  加入 `SubjectiveView`
- filter MUST NOT 修改 Ledger（保持 perception 只读）

### 5. Non-goals

- **不**实现 Phase 2 的 memory / orchestrator / metrics / social-graph / conversation /
  policy-hack / model-budget。本 change 只做**适配**与**审计**，为那 7 块铺平路径。
- **不**删除或重写 `CollapseService`。侦探引擎残留在本次审计中被**标注为
  "narrative 可选路径"**，与 measurement 路径解耦，不阻塞主路径。
- **不**改动 Lane Cove atlas 数据或导入管线。场地已决定为 Lane Cove；若后续
  需要另一场地，开独立 change。
- **不**选定 LLM provider 或 viz 前端。
- **不**修改任何已归档 change 的 spec。
- **不**对 `atlas` / `ledger` / `simulation` / `navigation` / `collapse` /
  `cartography` / `map-service` 的现有 Requirement 措辞做 BREAKING 改动。

## Capabilities

### New Capabilities
- `fitness-audit`: 用一组可执行的 acceptance test + 诊断脚本，逐条验证 Phase 1 基建
  能否承载三个实验；产出结构化 `fitness-report.json` 作为 Phase 2 开工的前置门禁
- `attention-channel`: 把"数字注意力 / 推送 / 算法偏向"提升为一级机制；定义
  `FeedItem` / `NotificationEvent` / `AttentionState` / `DigitalProfile` 与感知接入点

### Modified Capabilities
- `agent`: `AgentProfile` 新增结构性维度（ethnicity / tenure / income_tier /
  work_mode / digital），以及 `agent.population` 采样子模块；现有字段与行为保持
  兼容
- `perception`: `PerceptionPipeline` filter 链新增 `digital_attention` 插槽；
  `SubjectiveView.observations` 支持 `SenseType.DIGITAL`；物理感知不变

## Impact

### 受影响代码
- `synthetic_socio_wind_tunnel/agent/profile.py` — 新增结构字段 + DigitalProfile；
  `model_config = {"frozen": True}` 保持
- `synthetic_socio_wind_tunnel/agent/population.py`（新）— 按社区画像采样 1000 人
- `synthetic_socio_wind_tunnel/attention/` 新模块 — `models.py`（FeedItem 等）+
  `service.py`（feed 状态管理）
- `synthetic_socio_wind_tunnel/perception/filters/digital_attention.py`（新）
- `synthetic_socio_wind_tunnel/perception/models.py` — `SenseType` 加 `DIGITAL`
- `synthetic_socio_wind_tunnel/core/events.py` — 新增 `NOTIFICATION_RECEIVED` 等
  事件类型；不修改已有
- `tests/test_fitness_audit.py`（新）— 审计套件入口
- `tools/run_fitness_audit.py`（新）— 命令行驱动，产出 `fitness-report.json`
- `synthetic_socio_wind_tunnel/__init__.py` — re-export `DigitalProfile`、
  `AttentionState`、`FeedItem`、`NotificationEvent`

### 不受影响（保持兼容）
- Atlas / Ledger / Simulation / Navigation / Collapse / Cartography / MapService
  的现有 Requirement 与公共 API
- Lane Cove atlas 数据与连通度门禁
- 已归档 change 与 Phase 2 roadmap 的 stub

### 依赖变化
- 无新增第三方依赖。本 change 纯 Python + 已有 Pydantic。

### 风险
- **审计结论可能推翻 Phase 2 roadmap**：例如若"规模基线"在 Lane Cove 上就跑不满
  1000 agent × 288 tick，则 `orchestrator` change 的 tick 粒度需要重新设计。
  这正是本 change 存在的意义——把推翻发生在"设计 orchestrator 之前"而非之后。
- **DigitalProfile 的社会学正确性**：族裔 / 移民年限等字段触及敏感维度，
  本 change 只做"可观察事实字段"不做价值打分（与现有 affordance 的规则一致）；
  仍需在 design.md 中明确伦理边界。
