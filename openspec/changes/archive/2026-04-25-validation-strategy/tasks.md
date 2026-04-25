# Tasks — validation-strategy

冻结 validity taxonomy + audit 协议 + calibration target +
pre-publication checklist。**纯 spec + docs**；零代码 / 测试改动。

**Chain-Position**: `observability`（治理；约束所有 publishable 产出）
**前置**: `experimental-design` spec（已归档；本 change 是它的方法学
扩展）+ `metrics` spec（已归档；本 change 不改它）
**Fitness-report 锚点**: 不直接翻绿任何 audit；下游 calibration change
完成后通过本 spec 的 acceptance 间接 unblock
`phase1-baseline.profile-preset-ground-truthed`

## 1. Canonical 文档

- [x] 1.1 创建 `docs/agent_system/18-validation-strategy.md`：
  - **Part I**：6 种 validity 类别（接受 / 拒绝 / stub）
  - **Part II**：Stereotype audit 三协议（swap test / blind test /
    cross-model convergence）
  - **Part III**：Face validity protocol（Prolific N=20、5-Likert、
    阈值 3.5/5）
  - **Part IV**：Population calibration target（ABS Census 2021 SA2
    六维度 + chi-squared/KS 阈值）
  - **Part V**：Behavioral baseline calibration target（ABS Travel
    Survey OD + Google Popular Times EMD）
  - **Part VI**：Reproducibility lock 七字段
  - **Part VII**：Pre-publication checklist 8 项
  - **Part VIII**：与现有 spec / docs 的关系图（指向 00-thesis /
    13-research-design / 16-metrics）

## 2. spec 冻结

- [x] 2.1 (归档时自动) `openspec/specs/validation-strategy/spec.md`
  从 `specs/validation-strategy/spec.md` sync 创建（含 8 个
  Requirement）

## 3. 现有 docs 引用更新（仅引用，无内容改）

- [x] 3.1 `docs/agent_system/00-thesis.md` 的 "Research Posture" 章节：
  在末尾加 "Validity taxonomy 与 audit 协议 canonical 见
  [`18-validation-strategy.md`](18-validation-strategy.md)"
- [x] 3.2 `docs/agent_system/13-research-design.md` Part I "Research
  Posture"：补 "validity 6 类的取舍详见 18"
- [x] 3.3 `docs/agent_system/16-metrics.md` 的 "已知限制" 段：明示
  "metrics 内部一致性已由 cross-seed CI 覆盖；其它 5 类 validity 由
  18-validation-strategy 规定下游执行"
- [x] 3.4 `README.md` "Research Posture" 段：加一行
  "Validity taxonomy + audit protocols: see
  `docs/agent_system/18-validation-strategy.md`"
- [x] 3.5 `openspec/changes/phase-2-roadmap/proposal.md`：在
  `## Why` 末尾加一句 "publishable run 前置门禁——必须通过
  validation-strategy 的 8 项 pre-publication checklist；详见
  `openspec/specs/validation-strategy/spec.md`"

## 4. 验证

- [x] 4.1 `openspec validate validation-strategy --strict` 通过
- [x] 4.2 grep 检查：`synthetic_socio_wind_tunnel/` 下无任何 `.py` 文件
  diff（无代码改动）
- [x] 4.3 grep 检查：`tests/` 下无任何 `.py` 文件 diff（无测试改动）
- [x] 4.4 grep 检查：`openspec/specs/` 下已归档 capability spec 文件
  无 diff（experimental-design / metrics / multi-day-run / orchestrator
  / memory / agent / policy-hack / suite-wiring 等全部不动）
- [x] 4.5 Read `18-validation-strategy.md` 全文自检：8 个 Part 齐全；
  3 处 cross-link（00-thesis / 13-research-design / 16-metrics）正确

## 5. 全 pytest 回归

- [x] 5.1 `python3 -m pytest tests/ -q` —— 0 回归（本 change 不改代码 /
  测试）
- [x] 5.2 `make fitness-audit` —— 状态保持不变（无 capability 变化；
  下游执行才会改 audit 状态）
