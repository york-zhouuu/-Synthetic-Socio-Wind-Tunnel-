## 1. B4 conversation_topics（最小独立）

- [x] 1.1 新建 `data/lanecove/conversation_topics.json` 含 8-12 条 Lane Cove 特定话题（school zone / parking / Cameraygal Festival / data centre / Council elections / new cafe openings / bus changes / heritage bushland）
- [x] 1.2 新增 `data_loader/lanecove.py::load_conversation_topics()` 函数 + `__init__.py` re-export
- [x] 1.3 修改 `do_something` handler：args 接收 `local_topics`；prompt 加段
- [x] 1.4 新增 `tests/test_conversation_topics_load_and_inject.py`：load 返非空；handler prompt 含 topic
- [x] 1.5 跑测试，过

## 2. B3 social_priors audit

- [x] 2.1 新建 `tools/audit_social_priors.py`：load LANE_COVE_PROFILE × 1000 sample → compute_social_priors → 统计每 rule 产 ties 数 / 覆盖率
- [x] 2.2 跑一次记录基线
- [x] 2.3 新增 `tests/test_social_priors_audit.py`：每 rule 至少产 1 tie；总 ties 在合理区间（1000 agent 不应 > 100K ties）
- [x] 2.4 如发现异常，调 priors_per_agent_cap 等阈值

## 3. B1 archetype 扩展

- [x] 3.1 在 `data/lanecove/archetypes.json` 加 4 个 archetype：young_renter_commuter / mid_renter_family / older_renter_downsizer / casual_shift_worker
- [x] 3.2 新建 `tools/audit_archetype_coverage.py`：sample 1000 agent → match_archetype → 报覆盖率
- [x] 3.3 跑 audit 验证 matched ≥ 80%
- [x] 3.4 新增 `tests/test_archetype_coverage.py`：用 LANE_COVE_PROFILE 1000 sample 断言 matched ≥ 80%
- [x] 3.5 跑测试，过

## 4. B2 life_history templates

- [x] 4.1 新建 `data/lanecove/life_history_templates.json`：每个 archetype（11 个）对应 5-8 条 Lane Cove-grounded 第一人称生命事件模板
- [x] 4.2 修改 `data_loader/lanecove.py::_generate_life_history_for_one`：优先采样模板作 anchor，LLM 在模板上变奏；fallback 走原 LLM 即兴
- [x] 4.3 新增 `tests/test_life_history_templates.py`：每 archetype ≥ 5 条；{name}/{age} 渲染替换正确
- [x] 4.4 跑测试，过

## 5. 全量回归 + archive

- [x] 5.1 跑 `pytest tests/` 断言 ≥ 1218 passed（预期 +15..20 新测试）
- [x] 5.2 sync docs：`docs/agent_system/21-current-agent-design.md` §6 把 B1/B2/B3/B4 的 ❌ 改为 ✅ + 注明 2026-05-10 update
- [x] 5.3 跑 `openspec validate soul-memory-relations-completeness --strict`，过
- [x] 5.4 archive 到 `openspec/changes/archive/2026-05-10-soul-memory-relations-completeness/`
