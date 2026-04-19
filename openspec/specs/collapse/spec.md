# collapse — 薛定谔细节与证据蓝图

## Purpose
`engine.collapse.CollapseService` 实现"剧组模型"的导演：
房间细节、容器内物、物品纹理等在被首次观察时才由 LLM/回调生成，
生成后写入 Ledger 并永久化。Collapse 同时负责在生成容器内物时
注入"证据蓝图"（剧情必需线索）。

## Requirements

### Requirement: 懒生成入口（按目标类型三分）
CollapseService 不提供通用 `generate_detail`，而是按目标类型分三个方法：
- `examine_container(container_id, examiner)` — 首次检查触发容器内物生成。
- `examine_location_detail(location_id, examiner, detail_type=...)` — 生成房间/地点细节。
- `examine_item_detail(item_id, examiner)` — 生成物品的细颗粒描述。

所有方法 SHALL：
1. 先查 Ledger 是否已有对应 `GeneratedDetail`（`details_for(target_id)`），若有则直接返回；
2. 否则调用 `DetailGenerator` 回调（见下）生成内容；
3. 将结果封装为 `GeneratedDetail(is_permanent=True)` 写入 Ledger；
4. 对容器场景：同时更新 `ContainerState.contents_collapsed=True`、
   `collapsed_by`、`collapsed_at`。

#### Scenario: 两个 agent 先后检查同一物
- **WHEN** A 先 `examine_container("desk_drawer","A")`，B 后 `examine_container("desk_drawer","B")`
- **THEN** `DetailGenerator` SHALL 只被调用一次；B 拿到的 `GeneratedDetail` 与 A 相同

#### Scenario: 回调失败
- **WHEN** 回调抛出异常
- **THEN** Ledger SHALL 不被写入，上层接收到可重试的错误（不得写入半成品细节）

### Requirement: DetailGenerator 协议
CollapseService SHALL 在构造时或通过 `set_generator(gen)` 注入一个符合
`DetailGenerator(target_id, target_type, context: dict) -> str` 协议的回调。

- 内置 `default_generator` SHALL 返回可识别的占位符文本，便于无 LLM 环境下运行测试。

#### Scenario: 无生成器
- **WHEN** CollapseService 以 `generator=None` 构造
- **THEN** 默认使用 `default_generator`，返回 `"[Generated ... for ...]"` 形式的占位符

### Requirement: DirectorContext 为生成提供叙事指引
`DirectorContext` SHALL 提供字段：`narrative_hint`、`mood`、`tension_level`（0–1 浮点）、
`should_include`、`should_avoid`、`detail_level`、`writing_style`、`story_phase`、
`director_notes`。

- `DirectorContext.to_prompt_context()` SHALL 把非默认字段拼成适合嵌入 LLM prompt
  的文本。
- 所有字段 SHALL 为自由文本 / 枚举；`tension_level` 例外，允许数值供上层分段。

#### Scenario: 悬疑基调
- **WHEN** DirectorContext 的 `mood="ominous"`、`tension_level=0.8`
- **THEN** `to_prompt_context()` SHALL 包含 `"情绪基调: ominous"` 与 `"紧张程度: 高"`

### Requirement: 证据蓝图（EvidenceBlueprint）
`ledger.models.EvidenceBlueprint` 在 Ledger 中登记；CollapseService 在
`examine_container` 时 SHALL 查找 `required_in == container_id` 的蓝图，
并把 `must_contain` 作为 `CollapseContext.required_evidence` 传给生成回调。

- 当前 API **不**提供 `must_have_evidence(blueprint) -> bool` 式的独立校验方法。
  若未来需要前置校验，另开 change。

#### Scenario: 蓝图注入生成 prompt
- **WHEN** Linda 的办公桌抽屉有蓝图 `must_contain=["poison_bottle"]`
- **THEN** 首次 `examine_container("linda_desk_drawer", ...)` 的生成回调 SHALL 在
  `context["required_evidence"]` 中看到该条目

### Requirement: 空间预算约束
Collapse 在放置生成物时 SHALL 遵守 Atlas 容器的
`ContainerDef.item_capacity` / `surface_capacity`。

- `get_container_capacity_info(container_id)` SHALL 返回当前占用量与上限，
  供上层在调用前判断是否需要降级（改放其它位置）。
- `get_room_spatial_budget(room_id)` SHALL 返回房间内所有容器的聚合预算。

#### Scenario: 容器预算用尽
- **WHEN** 已满的抽屉被触发生成新物品
- **THEN** Collapse SHALL 拒绝注入（上层应获知该约束并降级）

### Requirement: 永久性与可追溯性
生成的 `GeneratedDetail` SHALL 记录 `generated_by`（首次触发的 examiner）
与 `generated_at`（时间戳），用于审计与罗生门效应验证。

- `is_permanent=True` 的细节 SHALL 不被后续 `examine_*` 调用覆盖。
- `has_been_examined(detail_id)` SHALL 返回是否已塌缩。

#### Scenario: 可追溯首位观察者
- **WHEN** 查询 `get_all_details_for("drawer_main")`
- **THEN** 返回的细节中 `generated_by` SHALL 为首次触发生成的 examiner
