## ADDED Requirements

### Requirement: Stereotype audit Part II 实施落地

publishable suite SHALL 通过 `data/calibration/stereotype_audit_report.json`
探测当前 stereotype audit 状态，对应 `validation-strategy` Part II 三协议
（swap / blind / cross-model）的实施落地。

publishable checklist 第 2 项（Stereotype audit passed）SHALL 当
stereotype_audit_report 的 `overall_passed: true` 时判 ✓；否则判 ✗。

acceptance 阈值 spec：
- swap test：`destination_overlap_pct ≥ 1 - threshold`，threshold 在
  stub mode 为 0.05、real_llm mode 为 0.10
- blind test：`destination_overlap_pct ≥ 0.80`
- cross-model：两 model 的 contest `evidence_alignment` 字段一致

任一协议 FAIL → checklist #2 ✗ → publishable suite report 顶部 SHALL
显示 `[unpublishable preview]` banner + disclosure 段列出 FAIL 协议 +
具体差异数值。

#### Scenario: 三协议全 pass → checklist #2 ✓
- **WHEN** stereotype_audit_report 含 `overall_passed: true`
- **THEN** publishable suite report.md 的 checklist #2 SHALL 显示 ✓；
  顶部 banner SHALL NOT 含 `[unpublishable preview]`（除非其它 checklist
  fail）

#### Scenario: 任一协议 FAIL → checklist #2 ✗
- **WHEN** stereotype_audit_report 含 `swap_test.passed: false`（即使
  blind / cross-model 都通过）
- **THEN** checklist #2 SHALL 显示 ✗；report.md 顶部 SHALL 含
  `[unpublishable preview]` banner；disclose 段 SHALL 列出哪个 axis 的
  哪个 swap pair fail 以及具体 behavioral_distance 数值

#### Scenario: 报告不存在 → checklist #2 ⚠️
- **WHEN** publishable suite 跑时 stereotype_audit_report.json 不存在
- **THEN** checklist #2 SHALL 显示 ⚠️ 状态："stereotype audit not run"；
  顶部 banner SHALL 含 `[unpublishable preview]` banner

#### Scenario: dev mode audit 不能用作 publishable 凭证
- **WHEN** stereotype_audit_report 含 `scale: "dev"`
- **THEN** publishable suite report SHALL 显示 ⚠️ "audit run in dev mode,
  not valid for publishable claim"；checklist #2 SHALL ✗
