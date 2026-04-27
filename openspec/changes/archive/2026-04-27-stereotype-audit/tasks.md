# Tasks — stereotype-audit

实施 `validation-strategy` Part II 三协议（swap / blind / cross-model），
解 publishable checklist #2。

**Chain-Position**: `infrastructure`
**前置**: `agent-calibration`（已 archive） + `agent-profile-enrich`
（已 archive，提供 gender + 13 swappable 字段）
**预计周期**: 1 周

## 1. audit 模块（阶段 1，1-2 day）

### 1.1 helper 函数
- [x] 1.1.1 新建 `synthetic_socio_wind_tunnel/agent/audit.py`：
  - `swap_profile_attribute(profile, attr, new_value) -> AgentProfile`
    用 `profile.model_copy(update={attr: new_value}, deep=True)`
  - `blind_profile_attribute(profile, attr) -> AgentProfile`
    把字段置 None
  - `BehavioralDistance` Pydantic model：destination_overlap_pct /
    encounter_count_delta_pct / n_agents / seed
  - `compute_behavioral_distance(run_a, run_b) -> BehavioralDistance`
    对比两次 sim 的目的地重合度 + encounter count
  - `AuditStatus` enum：PASS / FAIL
  - `assess_swap_acceptance(distance, *, mode) -> AuditStatus`
    阈值：stub 0.05 / real_llm 0.10
  - `assess_blind_acceptance(distance) -> AuditStatus`
    阈值：destination_overlap ≥ 0.80
  - `assess_cross_model_convergence(report_a, report_b) -> AuditStatus`
    比对 evidence_alignment 字段一致

- [x] 1.1.2 export 公共 API 到 `synthetic_socio_wind_tunnel/agent/__init__.py`

### 1.2 单元测试
- [x] 1.2.1 `tests/test_audit.py`：
  - `test_swap_profile_keeps_other_fields`：构造完整 profile → swap
    gender → 验证 13 维 enrich 字段全等
  - `test_blind_profile_keeps_other_fields`
  - `test_compute_behavioral_distance_identical`：两份相同 run → distance == 0
  - `test_compute_behavioral_distance_disjoint`：两份完全不同 run → distance == 1
  - `test_assess_swap_acceptance_stub_threshold`：边界值（0.04/0.05/0.06）
  - `test_assess_swap_acceptance_real_llm_threshold`：边界值（0.09/0.10/0.11）
  - `test_assess_blind_acceptance_threshold`：0.79/0.80/0.81
  - `test_cross_model_pass_when_evidence_match`
  - `test_cross_model_fail_when_evidence_mismatch`

## 2. CLI（阶段 2，1-2 day）

### 2.1 `tools/run_stereotype_audit.py`
- [x] 2.1.1 argparse：`--scale {dev|publishable}` / `--use-real-llm` /
  `--llm-provider` / `--seed-set`
- [x] 2.1.2 dev mode：1 seed × 20 agent × 3 day × stub-only
- [x] 2.1.3 publishable mode：2 seed × 100 agent × 14 day × require real LLM
- [x] 2.1.4 publishable scale 没传 `--use-real-llm` → sys.exit(2) + 诊断

### 2.2 swap test 实施
- [x] 2.2.1 跑 baseline run（无 swap）保存 trajectories
- [x] 2.2.2 对每个 swap pair：
  - clone profile pool + swap gender (male ↔ female 双向)
  - clone profile pool + swap ethnicity_group (Australia ↔ China,
    England ↔ Vietnam 各双向)
  - 跑同 seed sim
  - 算 behavioral_distance vs baseline
  - aggregate by axis（gender / ethnicity_group）
- [x] 2.2.3 swap_test 整体 pass 当所有 axis 都 pass

### 2.3 blind test 实施
- [x] 2.3.1 把全 1000 agent 的 ethnicity_group 置 None → 跑同 seed
- [x] 2.3.2 算 destination_overlap_pct vs baseline
- [x] 2.3.3 阈值判定 ≥ 0.80 → PASS

### 2.4 cross-model test 实施
- [x] 2.4.1 跑同 scenario × 同 seed × 两个 LLM provider（Anthropic Haiku
  + Gemini Flash）
- [x] 2.4.2 各自跑完 sim → 各自跑 contest scorer → 提取 evidence_alignment
- [x] 2.4.3 dev mode 跳过该协议（标 `state: "skipped (stub mode)"`）

### 2.5 JSON report 输出
- [x] 2.5.1 schema 按 design D8
- [x] 2.5.2 写入 `data/calibration/stereotype_audit_report.json`
- [x] 2.5.3 print 简洁 summary（哪些协议 pass / fail）

## 3. publishable suite report 接入（阶段 3，0.5 day）

### 3.1 改 `tools/run_variant_suite.py`
- [x] 3.1.1 读 `data/calibration/stereotype_audit_report.json`
- [x] 3.1.2 checklist #2 PASS/FAIL/N/A 写入 report.md
- [x] 3.1.3 disclose 段：FAIL 协议名 + 具体数值
- [x] 3.1.4 dev-mode-audit → ⚠️ "not valid for publishable"

## 4. 测试（阶段 4，0.5 day）

### 4.1 CLI 集成测试
- [x] 4.1.1 `tests/test_run_stereotype_audit.py`：
  - test_dev_mode_runs_in_under_30s
  - test_dev_mode_outputs_valid_json
  - test_publishable_without_use_real_llm_exits_2
  - test_report_schema_completeness（顶层 6 字段都在）

### 4.2 publishable suite 接入测试
- [x] 4.2.1 `tests/test_run_variant_suite.py` 或新加 audit 接入 test：
  - test_no_audit_report_yields_warning
  - test_failed_audit_yields_unpublishable_banner
  - test_passed_audit_yields_check_2_ok

## 5. 验证（阶段 5，0.5 day）

- [x] 5.1 全 pytest 通过（609+ tests + ~15 audit tests）
- [x] 5.2 `tools/run_stereotype_audit.py --scale dev` 跑通
- [x] 5.3 跑 stub-mode publishable suite 端到端：checklist #2 显示 ⚠️
  （audit not run）
- [x] 5.4 dev-mode audit 跑后 publishable suite 显示 ⚠️ "dev not valid"
- [x] 5.5 `openspec validate stereotype-audit --strict` 通过

### 5.x 真 LLM publishable mode（可选）
- [ ] 5.6 跑 `tools/run_stereotype_audit.py --scale publishable
  --use-real-llm --llm-provider gemini`（需要 `GEMINI_API_KEY` 和
  `ANTHROPIC_API_KEY`）—— 验证产出真 publishable audit report
  **[deferred: requires user-provided API keys + cost commitment]**
- [ ] 5.7 实测 cost 估算 vs $5-10 budget **[deferred]**

## 6. 文档

- [x] 6.1 `docs/agent_system/19-system-snapshot.md` 历史决策点表
- [x] 6.2 README 加一段 "How stereotype audit works"（可选，30 行）

## 7. archive sync

- [x] 7.1 archive 时把 delta specs 合入 main spec：
  `openspec/specs/agent/spec.md` + `openspec/specs/validation-strategy/spec.md`
- [x] 7.2 commit
