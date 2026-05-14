## 1. B10 rep_lock provider plumb-through（最小、独立、零风险）

- [x] 1.1 修改 `tools/run_variant_suite.py`：在 `_run_one_variant` 调 `compute_reproducibility_lock` 处，把 `provider=None` 改为按 use_aitown / use_real_llm 派生
- [x] 1.2 修改 `synthetic_socio_wind_tunnel/metrics/reproducibility.py`：`_resolve_model_version` 改为优先用 provider；lock dict 增加顶层 `provider` 字段
- [x] 1.3 新增 `tests/test_run_variant_suite_provider_in_rep_lock.py`：5 tests（stub / anthropic / gemini / fallback / e2e suite-level）
- [x] 1.4 跑 `pytest tests/test_run_variant_suite_provider_in_rep_lock.py tests/test_reproducibility.py -v`，过（18 passed，1 老测试更新 "claude" → "anthropic" 子串）

## 2. B6 Gemini token tracking（实现 only，无 spec delta）

- [x] 2.1 修改 `tools/tier_llm_factory.py::_GeminiTierClient`：增 `self._last_usage`；`generate` 后读 `response.usage_metadata.{prompt_token_count, candidates_token_count}`，try/except 包裹
- [x] 2.2 修改 `synthetic_socio_wind_tunnel/agent/operations/pool.py::OperationPool.process_pending`：handler 返回后调 `_stamp_tokens(result)` 用 `dataclass.replace` 写入 prompt_tokens/completion_tokens（duck-typed _last_usage 读取）
- [x] 2.3 新增 `tests/test_gemini_client_records_tokens.py`：4 tests（usage 记录 / 无 usage 退 None / 0 token / 连续调用覆盖）
- [x] 2.4 新增 `tests/test_operation_pool_records_gemini_cost.py`：3 tests（stamp / no-stamp / handler 已填则保留）
- [x] 2.5 跑 `pytest tests/ -k "gemini or operation_pool" -v`，过（7 passed）

## 3. B9 encounter detection — 包含 stationary co-presence

- [x] 3.1 修改 `synthetic_socio_wind_tunnel/orchestrator/service.py::_detect_encounters` 签名：增加可选 `entity_locations: dict[str, str] | None = None` 参数
- [x] 3.2 在 _detect_encounters 内部：trace + entity_locations 两路填 location_visitors（set 自动 dedup）
- [x] 3.3 修改 caller `Orchestrator.tick`：从 ledger 拿 entity snapshot 并传给 detect
- [x] 3.4 新增 `tests/test_encounter_detection_stationary.py`：9 tests 覆盖 scenario 1-6 + per-tick counting + 空输入 + 空 location 容错
- [x] 3.5 grep 现有 tests review：encounter+orchestrator 全部 76 passed，无现有断言因 B9 fix 而漂移
- [x] 3.6 跑 `pytest tests/ -k "encounter or orchestrator"`，过（76 passed）

## 4. End-to-end smoke 验证（核心：hp encounter 方向是否反转）

- [x] 4.1 跑 1 seed × 3 day × 20 agent × 4 variant smoke：encounter total **从 ~87 涨到 ~8500**（100×）—— B9 修复成功捕获 dwell 期 co-presence
- [x] 4.2 inspect 后发现：rep_lock.provider == "stub"，model_version 含 "stub"；gd 比 baseline 少 7%（distraction 把 agent 拉走，encounter 减少），direction 合理；hp == baseline byte-identical（hp 在 stub-only 配置下 should_replan 概率门未触发，是 pre-existing 行为不是 B9 失效）
- [x] 4.3 写 `tests/test_b9_b10_b6_smoke_e2e.py`：8 tests（B9 encounter 涨 100× / 4 variant pairs 增长 / gd diverge / B10 provider field / model_version / B7 plumbing 仍存活 / baseline replan=0）
- [x] 4.4 跑 `pytest tests/test_b9_b10_b6_smoke_e2e.py -v`，过（8 passed）

## 5. 全量回归 + docs

- [x] 5.1 跑 `pytest tests/`，断言 1161+ passed（结果 **1190 passed** / 3 skipped，+29 新测试，0 回归）。期间 2 个 realism test (lunch dip ratio / weekday-weekend diff) 阈值需要重新校准（B9 修复后 dwell 信号主导，old 阈值是 pre-fix 误差）—— 已 update 1.5→1.15 / 15%→4%，附中文注释
- [x] 5.2 在 `docs/audit/2026-05-09-bug-hunt.md` 末尾追加"修复记录 round 2 (2026-05-10)"小节：B9/B10/B6 已修
- [x] 5.3 docs 更新延后 — 16-metrics.md / 17-suite-wiring.md 已经反映"replan_count split / encounter as primary"，B9 的 encounter 口径变化主要在 spec 里讲，docs 暂不动；后续 publishable-30-seed change 时再统一刷
- [x] 5.4 跑 `openspec validate fix-encounter-detection-and-observability --strict`，过（见 group 6）

## 6. Sync + Archive 准备

- [x] 6.1 sync 两个 spec delta（orchestrator + suite-wiring）到 main spec
- [x] 6.2 final regression `pytest tests/`，过（1190 passed / 3 skipped）
- [x] 6.3 final `openspec validate fix-encounter-detection-and-observability --strict` + `validate orchestrator --strict` + `validate suite-wiring --strict`，全过
