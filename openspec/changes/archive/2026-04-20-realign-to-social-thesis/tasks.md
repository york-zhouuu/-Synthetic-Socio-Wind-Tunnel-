## 1. 基础搭建（模块骨架）

- [x] 1.1 创建 `synthetic_socio_wind_tunnel/attention/` 目录，含 `__init__.py` / `models.py` / `service.py`
- [x] 1.2 创建 `synthetic_socio_wind_tunnel/fitness/` 目录，含 `__init__.py` / `report.py` / `audit.py` / `driver.py`
- [x] 1.3 在 `core/errors.py` 的 `EventType` 中追加 `NOTIFICATION_RECEIVED` / `FEED_VIEWED` / `ATTENTION_TARGET_CHANGED`，补齐对应工厂函数 `create_notification_event`
- [x] 1.4 更新 `synthetic_socio_wind_tunnel/__init__.py`：re-export `FeedItem` / `NotificationEvent` / `AttentionState` / `DigitalProfile` / `AttentionService` / `FitnessReport` / `run_audit` / `PopulationProfile` / `sample_population`

## 2. AttentionChannel 数据模型

- [x] 2.1 定义 `FeedItem` Pydantic 模型（frozen，带 `hyperlocal_radius` 非负校验）
- [x] 2.2 定义 `NotificationEvent`（继承自 `WorldEvent`，properties 包含 feed_item_id + recipient_id）
- [x] 2.3 定义 `AttentionState`（`attention_target` 字面量；pending_notifications 为 tuple，确保可哈希）
- [x] 2.4 定义 `DigitalProfile`（所有字段带默认值，数值字段带 `ge=0` 校验）
- [x] 2.5 为上述模型写 `tests/test_attention_models.py`：构造、frozen、哈希、校验失败

## 3. AttentionService 实现

- [x] 3.1 在 `Ledger` 中添加 `notifications: list[NotificationEvent]` 字段及 CRUD（`add_notification` / `notifications_for`）
- [x] 3.2 实现 `AttentionService.inject_feed_item(item, recipients) -> list[NotificationEvent]`
- [x] 3.3 实现 `AttentionService.notifications_for(agent_id, *, since)` 与 `pending_for(agent_id)`
- [x] 3.4 实现 `_should_deliver(item, profile)` 纯函数与 `feed_bias_suppression` 概率注入
- [x] 3.5 实现 `export_feed_log(since, until) -> list[FeedDeliveryRecord]`
- [x] 3.6 写 `tests/test_attention_service.py`：覆盖推送按目标、偏向抑制统计性质、物理传播不被触发、日志导出

## 4. AgentProfile 结构性字段

- [x] 4.1 修改 `agent/profile.py`：追加 `ethnicity_group` / `migration_tenure_years` / `housing_tenure` / `income_tier` / `work_mode` / `digital` 字段，全部可选并带默认
- [x] 4.2 写 `tests/test_agent_profile_structural.py`：旧构造签名仍工作、负值校验拒绝、frozen 保持
- [x] 4.3 确认现有 `tests/test_agent_phase1.py` 全部仍 PASS

## 5. Population 采样

- [x] 5.1 创建 `agent/population.py`：定义 `PopulationProfile` 与 `DigitalParams`
- [x] 5.2 实现 `sample_population(profile, *, seed)` 使用 `random.Random(seed)` 保证确定性
- [x] 5.3 实现权重归一校验（总和 1.0 ± 1e-6）
- [x] 5.4 定义 `LANE_COVE_PROFILE` preset（先用占位分布，数值留 TODO 注释标出）
- [x] 5.5 定义 `ZETLAND_PROFILE` preset 的 schema，所有分布标 `# placeholder for future change`
- [x] 5.6 实现 `num_protagonists` 参数：从样本中随机选 N 个置 `is_protagonist=True` 并切换 `base_model`
- [x] 5.7 写 `tests/test_agent_population.py`：确定性、分布覆盖、主角分配

## 6. ObserverContext & AgentRuntime 接入

- [x] 6.1 修改 `perception/models.py`：`ObserverContext` 追加 `digital_state` 字段（默认 None）
- [x] 6.2 在 `perception/models.py` 的 `SenseType` 枚举追加 `DIGITAL`
- [x] 6.3 为 `SubjectiveView` 加 `get_observations_by_sense(sense)` 便利方法（若已有则跳过）
- [x] 6.4 修改 `agent/runtime.py` 的 `build_observer_context`：当注入了 AttentionService 时合成 AttentionState；未注入时为 None
- [x] 6.5 写 `tests/test_observer_context_digital.py`：默认 None 路径、注入后 pending 正确

## 7. DigitalAttentionFilter

- [x] 7.1 创建 `perception/filters/digital_attention.py`，继承 `filters.base.PerceptionFilter`
- [x] 7.2 实现 "`digital_state is None` 透传" 分支
- [x] 7.3 实现 "`phone_feed` 时物理 notable 按 `attention_leakage` 下降"（注入 RNG 以便测试确定性）
- [x] 7.4 实现 "pending 推送 → `Observation(sense=DIGITAL)` 注入"；根据 `notification_responsiveness` 与 `attention_target` 打 `missed` tag
- [x] 7.5 修改 `perception/pipeline.py`：构造器加 `include_digital_filter: bool = False`，启用时把 filter 加入链
- [x] 7.6 写 `tests/test_digital_attention_filter.py`：透传、刷手机注意力漏损期望值、推送注入正确性、missed tag

## 8. Fitness Audit — 核心框架

- [x] 8.1 在 `fitness/report.py` 定义 `FitnessReport` / `AuditResult` / `CategoryResult` Pydantic 模型
- [x] 8.2 在 `fitness/driver.py` 实现 `_MinimalTickDriver`：手工 `advance_time` + 逐 agent 调 `simulation.move_entity` + 手工触发 `pipeline.render`
- [x] 8.3 在 `fitness/audit.py` 实现 `run_audit(atlas_path, *, scale, output_path) -> FitnessReport` 入口
- [x] 8.4 实现 `AuditResult.to_dict` 与 `FitnessReport.to_json` 原子写文件
- [x] 8.5 写 `tests/test_fitness_report.py`：schema 稳定性、原子写、读回验证

## 9. Fitness Audit — E1 / E2 / E3 测试实现

- [x] 9.1 实现 `audit_e1_digital_lure`：push-reaches-target / push-respects-attention-state / feed-log-extractable
- [x] 9.2 实现 `audit_e2_spatial_unlock`：door-unlock-midrun / path-diff-extractable / desire-path-detectable
- [x] 9.3 实现 `audit_e3_shared_perception`：looking-for-propagation / shared-task-memory-seam（后者 skip + mitigation_change="memory"）
- [x] 9.4 写 `tests/test_fitness_e1_e2_e3.py`：在 Lane Cove atlas 小子集上跑三组 audit，断言 `pass` 集合与预期一致

## 10. Fitness Audit — Profile / Ledger / Site / Scale / Cost

- [x] 10.1 实现 `audit_profile_distribution`：采样 1000 agent 后检查结构性维度覆盖率 100%、`daily_screen_hours` 标准差 ≥ 1.5
- [x] 10.2 实现 `audit_ledger_observability`：`export_trajectories` / `export_encounters` / `snapshot-determinism`
- [x] 10.3 实现 `audit_site_fitness`：在 atlas 上计算 named_building_ratio / residential_ratio / density；附 `zetland_gap_notes`
- [x] 10.4 实现 `audit_scale_baseline`：quick = 100 × 72 的 wall p50/p99；full 开关位于 CLI
- [x] 10.5 实现 `audit_cost_baseline`：用 token 估算 + 固定常量价格，给每日 cost 上下界
- [x] 10.6 写 `tests/test_fitness_profile_ledger_site_scale.py`：每类 audit 的断言都至少有 1 条 `pass` 和 1 条 `fail` 路径覆盖

## 11. 命令行与工件持久化

- [x] 11.1 创建 `tools/run_fitness_audit.py`：`argparse` 支持 `--scale`、`--category`、`--full`、`--output`
- [x] 11.2 默认输出到 `data/fitness-report.json`（已加入 `.gitignore`；commit 时决定是否提交；本 change 不 commit）
- [x] 11.3 添加 Makefile 目标 `make fitness-audit` 调用上述脚本
- [x] 11.4 在 README 增加一节 "Fitness audit" 说明运行方法与报告解读

## 12. Phase 2 前置门禁接入

- [x] 12.1 修改 `openspec/changes/phase-2-roadmap/tasks.md`：每块能力的"写独立 proposal"任务后追加子任务 "引用 `fitness-report.json` 中对应 `fail`/`skip` 条目作为动机"
- [x] 12.2 在 `openspec/changes/phase-2-roadmap/proposal.md` 的 `## Why` 末尾加一段："Phase 2 的每块 change 的动机 SHALL 至少引用一条审计失败条目"
- [x] 12.3 在 `docs/WIP-progress-report.md` 末尾加 "Phase 1.5 审计结论" 一节（由 audit 首次运行后填充）

## 13. 集成与回归

- [x] 13.1 运行完整测试套件 `python -m pytest tests/ -v`，确保 Phase 1 所有测试仍 PASS
- [x] 13.2 运行 `make fitness-audit`（quick），确认产出 `fitness-report.json`，手工检查每个 category 至少 1 条结果
- [x] 13.3 手工对照 `FitnessReport` 结构与 `fitness-audit` spec 中 schema 描述，修正偏差
- [x] 13.4 更新 `synthetic_socio_wind_tunnel/__init__.py`：检查是否漏掉任何新公共 API 的 re-export；运行 `python -c "from synthetic_socio_wind_tunnel import *"` 确认

## 14. Archive 准备

- [x] 14.1 确认所有 `fitness-report.json` 中 `status="fail"` 条目都填了 `mitigation_change` 字段
- [x] 14.2 运行 `openspec validate realign-to-social-thesis` 无错误
- [ ] 14.3 编写 PR 描述，引用 proposal / design 的关键决策（D1–D8）
- [x] 14.4 在 `docs/agent_system/` 下新增 `07-审计报告解读.md`（一页），说明如何使用 fitness report 驱动后续 change
