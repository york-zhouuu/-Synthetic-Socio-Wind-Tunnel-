# Tasks — publishable-finalize

实施 reproducibility lock 7 字段 + ethics auto-inject，解 publishable
checklist #6/#7。

**预计周期**: 0.5 day

## 1. ethics 常量

- [x] 1.1 新建 `synthetic_socio_wind_tunnel/metrics/ethics.py`
  - `ETHICS_STATEMENT: str` = research-design Part V verbatim 文本
  - export via `synthetic_socio_wind_tunnel/metrics/__init__.py`

## 2. reproducibility helper

- [x] 2.1 新建 `synthetic_socio_wind_tunnel/metrics/reproducibility.py`：
  - `_hash_prompt_template() -> str`
  - `_hash_profile(profile: PopulationProfile) -> str`
  - `_hash_variants(names: list[str]) -> dict[str, str]`
  - `_resolve_model_version(use_real_llm: bool, provider: str) -> str`
  - `_git_rev_parse_head() -> str`（fallback "unknown"）
  - `compute_reproducibility_lock(...) -> dict[str, Any]` 主入口

## 3. 接入 suite

- [x] 3.1 改 `tools/run_variant_suite.py`：
  - 计算 reproducibility lock（每个 variant + suite-level 都需要）
  - 把 7 字段塞进 RunMetrics.extensions 与 SuiteAggregate metadata

- [x] 3.2 改 `synthetic_socio_wind_tunnel/metrics/report.py::write_markdown`：
  - 在 banner 之后、checklist 之前注入 ethics statement section
  - 在 checklist 之后注入 `### Reproducibility Lock` 表格
  - checklist #6 / #7 状态自动从 ⚠️ → ✓

## 4. 测试

- [x] 4.1 `tests/test_reproducibility.py`：
  - test_compute_reproducibility_lock_all_seven_fields
  - test_prompt_template_hash_stub_mode
  - test_prompt_template_hash_real_mode
  - test_profile_hash_changes_with_profile
  - test_git_rev_parse_fallback_unknown
  - test_variants_loaded_dict
- [x] 4.2 `tests/test_metrics_ethics.py`：
  - test_ethics_statement_constant_exists
  - test_ethics_contains_required_keywords ("云室", "dual-use")
- [x] 4.3 `tests/test_metrics_models.py` 或同类扩展：
  - test_report_contains_ethics_section
  - test_report_contains_reproducibility_lock

## 5. 验证

- [x] 5.1 全 pytest 通过
- [x] 5.2 跑 dev mode suite → 验证 report.md 含两块 + checklist #6/#7 ✓
- [x] 5.3 `openspec validate publishable-finalize --strict` 通过

## 6. 文档

- [x] 6.1 更新 `docs/agent_system/19-system-snapshot.md`

## 7. archive sync

- [x] 7.1 archive 时合 delta spec 入 `openspec/specs/validation-strategy/spec.md`
- [x] 7.2 commit
