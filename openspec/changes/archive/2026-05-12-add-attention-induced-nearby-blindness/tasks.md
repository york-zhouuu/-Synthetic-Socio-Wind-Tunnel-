## 1. NoticingGate module（new capability）

- [x] 1.1 新建 `synthetic_socio_wind_tunnel/attention/noticing.py`：定义常量
- [x] 1.2 实现 `noticing_prob(a, b)` 与 `noticed_pair(a, b, *, seed, day, tick, pair)` (deterministic hash-based RNG)
- [x] 1.3 实现 `compute_notification_delta(urgency, responsiveness, openness)`
- [x] 1.4 实现 `baseline_screen_share(digital_profile)`
- [x] 1.5 新增 `tests/test_attention_noticing.py`：17 scenario PASS

## 2. AttentionService phone_attention state

- [x] 2.1 添加 `_phone_attention` / `_phone_attention_baseline` / `_personality_openness` 字段（含 __slots__ 更新）
- [x] 2.2 `set_phone_attention_baseline`、`set_personality_openness`、`get_phone_attention`
- [x] 2.3 `tick_decay_all()`
- [x] 2.4 `deliver_feed_item` 成功 deliver 后调 `_accumulate_phone_attention`
- [x] 2.5 attention_service tests 不 regress

## 3. SocialGraphService 拆 physical / noticed

- [x] 3.1 `record_noticed_encounter`（grow_strength=True）+ `record_encounter` 别名
- [x] 3.2 `record_physical_encounter`（grow_strength=False，记入 `_physical_only_count`，不创建 Tie 或不增 strength）
- [x] 3.3 Tie 不动；用 side dict `_physical_only_count` 追踪 + `total_physical_only_encounters` 属性
- [x] 3.4 现有 social_graph + memory_social_graph tests 不 regress

## 4. MemoryService.process_tick wiring

- [x] 4.1 在 process_tick 开头调 `attention_service.tick_decay_all()`
- [x] 4.2 encounter 循环：调 `_is_encounter_noticed` → record_noticed 或 record_physical
- [x] 4.3 加 `_noticing_seed` 字段 + __slots__ 更新

## 5. Metrics 新字段（deferred — current run via _physical_only_count adequate）

- [~] 5.1-5.4 通过 social_graph.total_physical_only_encounters + Tie 列表已暴露；
  RunMetrics typed 字段下一轮 change 再加；audit 工具直接读 social_graph

## 6. Suite wiring + baseline initialization

- [x] 6.1 `tools/run_variant_suite.py`：sample_population 后给 attention_service 注入每 agent baseline + openness + digital profile
- [x] 6.2 `phone_friction.apply_intervention_start` 同步更新 attention_service baseline + profile（关键！否则 friction 不传导到 noticing gate）
- [~] 6.3 `run_multi_day_experiment.py` / `replan_trace.py`：可走 deprecation 路径

## 7. Audit + smoke 验证

- [x] 7.1 `tools/audit_realism_systemic.py` 未改（独立 audit OK，noticing 指标通过下面 smoke 直读 graph 验证）
- [x] 7.2 **smoke 实测 thesis 方向正确**：
   - `pf.noticed_enc = 3387 (+21.2% vs baseline 2794)` ✓ thesis 预期
   - `gd.noticed_enc = 2578 (-7.7% vs baseline)` ✓ thesis 预期
   - `pf.noticing_rate = 24.8%` > `baseline 20.3%` > `gd 20.0%` ✓
- [x] 7.3 `python -m pytest tests/` 全套：**1334 passed, 3 skipped, 0 failed**

## 8. 文档 + archive

- [ ] 8.1 更新 `docs/agent_system/00-thesis.md`（待加 attention-induced-noticing-gate 链路段）
- [ ] 8.2 更新 `docs/audit/2026-05-12-deep-issues.md`：标 A1 RESOLVED + 数据
- [ ] 8.3 archive 该 change（等 §8.1-8.2 文档完成）
