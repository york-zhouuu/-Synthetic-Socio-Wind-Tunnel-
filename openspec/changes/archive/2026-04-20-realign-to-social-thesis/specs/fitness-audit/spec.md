# fitness-audit — 能力增量

## ADDED Requirements

### Requirement: 审计入口与结构化产物

系统 SHALL 提供 `synthetic_socio_wind_tunnel.fitness.audit.run_audit(
atlas_path: Path, *, scale: Literal["quick", "full"] = "quick",
output_path: Path | None = None) -> FitnessReport`，
以真实 atlas 为输入，产出符合 `FitnessReport` schema 的结构化结果。

- `FitnessReport.schema_version` SHALL 为字符串，当前 `"1.0"`。
- `FitnessReport.categories` SHALL 至少包含（分三组）：
  - **基线存在性**：`phase1-baseline`、`phase2-gaps`
  - **集成**：`e1-digital-lure`、`e2-spatial-unlock`、`e3-shared-perception`、
    `profile-distribution`、`ledger-observability`
  - **诊断**：`site-fitness`、`scale-baseline`、`cost-baseline`
- 每条条目 SHALL 为 `AuditResult(id, status, detail, mitigation_change | None)`。
  `status in {"pass", "fail", "skip"}`。
- 当 `output_path` 给定时 SHALL 原子写入 JSON；不给定时仅返回对象。

#### Scenario: 基线快速运行
- **WHEN** 在 Lane Cove atlas 上调用 `run_audit(atlas_path, scale="quick")`
- **THEN** 返回的 `FitnessReport` SHALL 覆盖全部 8 个 category，
  每条 `AuditResult` SHALL 具备非空 `id` 与 `status`

#### Scenario: 失败条目带修复指向
- **WHEN** `e1-digital-lure` 中 `push-reaches-target` 失败（因为当前未建 attention-channel）
- **THEN** 该 AuditResult 的 `mitigation_change` SHALL 非空（指向
  `realign-to-social-thesis` 或后续 Phase 2 change 名）

### Requirement: Phase 1 基线存在性探针

审计 SHALL 提供 `phase1-baseline` category，对关键能力做存在性检查
（import 模块、查 AgentProfile / ObserverContext / SenseType / EventType
等的字段集合），而**不调用**新能力的任何功能。目的是避免"自我合理化
套娃"——如果 audit 用 AttentionService 验证 AttentionService 是否工作，
Phase 1 裸代码的缺口就无法被发现。

- 每条探针 SHALL 返回 PASS 当且仅当目标模块 / 字段 / 枚举值在当前
  Python 进程可见；否则 FAIL，`mitigation_change` 指向提供该能力的 change。
- 至少覆盖：`attention-module` / `attention-service` / `feed-item-model` /
  `notification-event-type` / `observer-digital-state` / `sense-digital` /
  `digital-attention-filter` / `population-sampler`、
  `profile-{ethnicity-group,housing-tenure,income-tier,work-mode,digital-field}`、
  `fitness-audit`。
- 允许保留 "应当 FAIL 的真实缺口"（例如
  `profile-preset-ground-truthed`：Lane Cove preset 是未校准占位），
  供后续 change 作为锚点。

#### Scenario: 关键模块存在探针
- **WHEN** 在 realign-to-social-thesis 应用后的代码库上跑 audit
- **THEN** `phase1-baseline.attention-module` SHALL 为 PASS；
  `phase1-baseline.sense-digital` SHALL 为 PASS

#### Scenario: 未校准的 preset 仍 FAIL
- **WHEN** `phase1-baseline.profile-preset-ground-truthed` 被评估
- **THEN** SHALL 为 FAIL，`mitigation_change="agent"`，提示需 ABS 校准

### Requirement: Phase 2 缺口探针

审计 SHALL 提供 `phase2-gaps` category，每条对应
`openspec/changes/phase-2-roadmap/` 声明的一个 capability
（`orchestrator` / `memory` / `social-graph` / `model-budget` /
`policy-hack` / `conversation` / `metrics`）。

- 每条探针在该 capability 的模块路径 `synthetic_socio_wind_tunnel.<cap>`
  不存在时 FAIL，`mitigation_change` 指向该 capability 名。
- 实现落地后（模块 importable），探针自动转为 PASS——这即为"该 Phase 2
  change 已完成"的自动检测信号。
- 此 category 为 Phase 2 change 的 `## Why` 提供**固定锚点集**——每块
  Phase 2 change 至少能引用到一条 FAIL AuditResult，不会出现"锚点缺失"。

#### Scenario: 新能力未实现时 FAIL
- **WHEN** `synthetic_socio_wind_tunnel.orchestrator` 模块不存在
- **THEN** `phase2-gaps.orchestrator` SHALL 为 FAIL，
  `mitigation_change="orchestrator"`

#### Scenario: 锚点覆盖率完整
- **WHEN** 运行 `phase2-gaps` category
- **THEN** AuditResult 的 `mitigation_change` 集合 SHALL 覆盖所有 7 个
  Phase 2 capability

### Requirement: E1 Digital Lure 可行性检查

审计 SHALL 验证"Experiment 1 数字诱饵"所需的基建能力：

- **push-reaches-target**：能否把一条 `NotificationEvent` 以 "hyperlocal radius"
  的语义送达**范围内** agent 的 `SubjectiveView`，且不送达范围外 agent。
- **push-respects-attention-state**：当 agent `AttentionState.attention_target
  != phone_feed` 时，推送 SHALL 以较低 `confidence` 出现，或被标记 `missed=True`。
- **feed-log-extractable**：能否从 Ledger / 事件流中导出每个 agent 收到的
  FeedItem 序列（供后续 metrics 算扩散）。

#### Scenario: 推送按半径分割受众
- **WHEN** 审计在 Lane Cove atlas 随机位置注入一条 `radius=300m` 的推送，
  并以 10 个 agent 分布（5 近 5 远）跑最小 tick
- **THEN** 近端 5 个 agent 的 SubjectiveView SHALL 出现该 FeedItem，
  远端 5 个 SHALL 不出现；此条 AuditResult SHALL 为 `pass`

#### Scenario: 手机锁屏状态时推送被标记 missed
- **WHEN** agent 的 `attention_target=physical_world` 且 `notification_responsiveness=0.0`
- **THEN** 推送 FeedItem 在 SubjectiveView 中 SHALL 带 `missed=True` 标记

### Requirement: E2 Spatial Unlock 可行性检查

审计 SHALL 验证"Experiment 2 空间解锁"所需的基建能力：

- **door-unlock-midrun**：能否在运行期对一扇原先 `is_locked=True` 的门调用
  `SimulationService.unlock_door` 并让 `NavigationService.find_route` 在
  下一次调用时把该门作为可通行节点。
- **path-diff-extractable**：能否从 Ledger 导出"解锁前 agent 绕行距离"与
  "解锁后 agent 绕行距离"的差值（供轨迹偏移指标原料）。
- **desire-path-detectable**：`LocationVisibility` / `AgentKnowledgeMap`
  能否记录"新发现的通路"作为 `learned_from="desire_path_opened"`。

#### Scenario: 解锁后立即反映在路由
- **WHEN** 一扇连接 block_a 与 block_b 的门在 tick N 被 unlock_door
- **THEN** tick N+1 的 `NavigationService.find_route(block_a, block_b,
  strategy=SHORTEST)` SHALL 包含该门作为 `open_door` step，
  `total_distance` SHALL 小于 unlock 之前

### Requirement: E3 Shared Perception 可行性检查

审计 SHALL 验证"Experiment 3 共同感知"所需的基建能力：

- **looking-for-propagation**：对一组 agent 统一设置 `ObserverContext.looking_for`
  后，它们对同一 atlas 对象的 SubjectiveView SHALL 具备可对齐的
  `Observation.tags` 或 `is_notable` 提升。
- **shared-task-memory-seam**：当前 Phase 1 无持久 task 存储；审计 SHALL
  记录此条为 `skip` 并 `mitigation_change="memory"`（Phase 2 memory change）。

#### Scenario: 共同寻找线索时 notable 被统一提升
- **WHEN** 3 个 agent 的 `looking_for=["lost_cat_poster"]`，且 atlas 某墙面
  被打上该标签
- **THEN** 3 个 agent 的 SubjectiveView 中该墙面的 Observation SHALL 都具备
  `is_notable=True`

#### Scenario: 共享任务持久化暂缺
- **WHEN** 审计检查"任务在 tick 之间持久化"
- **THEN** 该 AuditResult SHALL 为 `skip`，`mitigation_change` SHALL 指向
  Phase 2 的 `memory` 或 `policy-hack` change

### Requirement: Profile 分布审计

审计 SHALL 验证 `agent.population` 采样模块能产出满足 thesis 假设的
人群异质性：

- **structural-dims-populated**：1000 agent 样本中，`ethnicity_group` /
  `housing_tenure` / `income_tier` / `work_mode` 的**每个可能值**
  SHALL 至少出现 1 次（覆盖率 100%）。
- **digital-profile-variance**：1000 agent 的 `digital.daily_screen_hours`
  分布的标准差 SHALL ≥ 1.5（即非常集中的分布会被判 fail）。
- **language-coverage-matches-site**：对 Lane Cove 采样时，至少包含 English
  加一门亚裔语言；对 Zetland profile（未来）SHALL 更偏多语种。

#### Scenario: 结构性维度覆盖
- **WHEN** 审计用默认 seed 采样 1000 Lane Cove agent
- **THEN** `ethnicity_group`, `housing_tenure`, `income_tier`, `work_mode`
  4 个维度各自的值集合 SHALL 与配置声明一致

### Requirement: Ledger 可观测性审计

审计 SHALL 验证能从 Ledger 无侵入地导出 Phase 2 metrics 所需原料：

- **trajectory-export**：对指定 agent 在指定 tick 范围内的
  `(tick, location_id, position, activity)` 序列 SHALL 可导出为 DataFrame/CSV。
- **encounter-export**：同一 `location_id` 上的 agent 对 SHALL 可以按 tick
  聚合导出，作为"路径相遇"候选（orchestrator 未建时用这个代替）。
- **snapshot-determinism**：给定固定 seed 与 atlas，两次跑 quick 审计的
  导出 SHALL 逐字节一致。

#### Scenario: 轨迹导出
- **WHEN** 审计用 10 agent × 72 tick 跑一次后调用
  `export_trajectories(ledger, agent_ids, tick_range)`
- **THEN** 返回的结构 SHALL 是 `list[TrajectoryPoint]` 或 DataFrame，
  行数 SHALL 等于 agent 数 × tick 数

### Requirement: Site fitness 报告

审计 SHALL 对 Lane Cove atlas 产出纯数据诊断（不通过/不失败；仅陈述）：

- `named_building_ratio`
- `residential_ratio`
- `density_buildings_per_km2`
- `notes`: 字符串列表，仅在极端情况（atlas 为空、密度异常低）下填写。
  MUST NOT 做跨场地对比或 thesis judgement——场地已锚定 Lane Cove。

此条 Requirement 的诊断 SHALL 以 `status="pass"` 输出（不门禁）。

#### Scenario: Lane Cove 场地诊断不阻塞
- **WHEN** 审计在 Lane Cove atlas 上跑完
- **THEN** `site-fitness` category 的所有 AuditResult `status` SHALL 为 `pass`，
  `detail` 包含可读数值

### Requirement: 规模与成本基线

审计 SHALL 测 Lane Cove atlas 上的**规模基线**与**成本基线**：

- **scale-baseline**：`scale="quick"` 下 100 agent × 72 tick 的 wall 时间 p50/p99；
  `scale="full"` 下 1000 agent × 288 tick 的同样指标（可选跑）。
- **cost-baseline**：不实际调用 LLM，仅**估算**——按 `ModelDecisionStub`
  在审计里模拟 "每 agent 每天 N 次 sonnet 调用 / M 次 haiku" 的 token 用量，
  乘以常量价格，输出日成本上下界。

#### Scenario: quick 规模基线在 CI 下可跑
- **WHEN** CI 环境调用 `run_audit(scale="quick")`
- **THEN** 结果 SHALL 在单机 60 秒内返回；`scale_baseline.wall_seconds_p99`
  SHALL 非空

### Requirement: 审计作为 Phase 2 前置门禁

`openspec/changes/phase-2-roadmap/tasks.md` SHALL 被更新：每块能力的
独立 proposal 开工前，必须引用 `fitness-report.json` 中对应 `fail`
或 `skip` 条目作为其 `## Why`。审计报告的 `mitigation_change` 字段
SHALL 为这种引用提供指向。

#### Scenario: memory change 引用审计
- **WHEN** Phase 2 的 `memory` change 被提案
- **THEN** 其 `proposal.md` 的 `## Why` SHALL 至少引用
  `fitness-report.json` 中一条 `mitigation_change == "memory"` 的 AuditResult
