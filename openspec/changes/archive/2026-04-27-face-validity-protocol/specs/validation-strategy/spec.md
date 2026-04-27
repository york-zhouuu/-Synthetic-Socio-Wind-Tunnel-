## ADDED Requirements

### Requirement: Face Validity Protocol Part III 实施落地

publishable suite SHALL 通过
`data/calibration/face_validity_report.json` 探测 face validity 状态，
对应 `validation-strategy` Part III 协议（M=10 narrative × N=20 真人评分）。

publishable checklist 第 3 项 SHALL 当 face_validity_report 含
`passed: true` 时判 ✓；否则 ✗ / ⚠️。

acceptance 阈值（spec Part III）：
- 200 ratings 整体 avg ≥ 3.5/5（authenticity + realism 题平均）
- ≤ 20% ratings 评 ≤ 2

#### Scenario: 报告 passed 状态 → checklist #3 ✓
- **WHEN** face_validity_report 含 `passed: true`
- **THEN** suite report.md checklist #3 SHALL 显示 ✓ + avg + pct_low 数值

#### Scenario: 报告 failed → checklist #3 ✗
- **WHEN** face_validity_report 含 `passed: false`
- **THEN** checklist #3 SHALL 显示 ✗；report.md 顶部 SHALL 含
  `[unpublishable preview]` banner；disclosure 段 SHALL 列出
  failing 原因（avg 太低 / pct_low 太高）

#### Scenario: 报告不存在 → checklist #3 ⚠️
- **WHEN** publishable suite 跑时 face_validity_report.json 不存在
- **THEN** checklist #3 SHALL 显示 ⚠️ "face validity not run; see
  docs/face_validity/01-protocol.md"


### Requirement: Face Validity 入口与出口 CLI

`tools/sample_face_validity.py` SHALL 是采样 narrative + 生成
Prolific-ready 题目模板的唯一 CLI。

`tools/aggregate_face_validity.py` SHALL 是读取 Prolific scores CSV
+ 聚合 → 输出 face_validity_report.json 的唯一 CLI。

中间人类流程（Prolific 招募 / 答题）外置；本 spec 只规定两端代码合约。

#### Scenario: 采样 CLI 输出 M=10 + 每 variant ≥ 1
- **WHEN** 跑 `python3 tools/sample_face_validity.py --suite-dir <suite>
  --output narratives.json`
- **THEN** narratives.json SHALL 含 10 条 narrative；suite 中每个 variant
  SHALL 至少 1 条覆盖

#### Scenario: 聚合 CLI 输出合规 JSON
- **WHEN** 跑 `python3 tools/aggregate_face_validity.py --scores-csv
  <csv> --narratives <json> --output report.json`
- **THEN** 输出 face_validity_report.json SHALL 含 `passed: bool` /
  `overall_avg: float` / `pct_low: float` / `n_narratives: int` /
  `n_reviewers: int` 字段
