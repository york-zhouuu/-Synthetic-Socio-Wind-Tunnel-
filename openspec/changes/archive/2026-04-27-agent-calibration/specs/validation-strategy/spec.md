## ADDED Requirements

### Requirement: Calibration Part IV/V 实施落地

publishable suite SHALL 通过 `data/calibration/calibration_report.json`
探测当前 calibration acceptance 状态（`strict` / `best-effort` / `failing`），
对应 `validation-strategy` Part IV (Population) 与 Part V (Behavioral) 的
实施落地。

publishable checklist 第 1 项（Calibration passed）SHALL 当 calibration_report
的 `population.acceptance_level` 与 `behavioral.acceptance_level` 都至少为
`best-effort` 时判 ✓；否则判 ✗。

#### Scenario: best-effort 通过 → checklist #1 ✓
- **WHEN** `data/calibration/calibration_report.json` 含
  `population.acceptance_level: "best-effort"` 与
  `behavioral.acceptance_level: "best-effort"`
- **THEN** publishable suite report 的 checklist #1 SHALL 显示 ✓；
  report.md SHALL 在 calibration section 列出未通过的具体维度

#### Scenario: 任一维度 failing → checklist #1 ✗
- **WHEN** population 或 behavioral 任一为 `failing`
- **THEN** publishable suite report SHALL 显示 ✗ + `[unpublishable preview]`
  顶部 banner

#### Scenario: report 是已知状态而非每次重算
- **WHEN** `tools/run_variant_suite.py --mode publishable` 跑
- **THEN** 它 SHALL 读 `data/calibration/calibration_report.json` 引到最终
  report；MUST NOT 触发 calibration 重计算（calibration 是离线 CLI 单独跑）
