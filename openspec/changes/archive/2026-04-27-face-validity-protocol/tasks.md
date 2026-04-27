# Tasks — face-validity-protocol

实施 publishable checklist #3 的两端代码（采样 + 聚合）；中间人类流程外置。

**预计周期**: 0.5 day 代码 + 1-3 day Prolific 人力

## 1. face_validity 模块

- [x] 1.1 新建 `synthetic_socio_wind_tunnel/metrics/face_validity.py`：
  - `Narrative` Pydantic model：agent_id / variant_name / summary_text /
    profile_excerpt
  - `Score` model：reviewer_id / narrative_id / authenticity / realism /
    free_text
  - `FaceValidityStatus` model：passed / overall_avg / pct_low /
    n_narratives / n_reviewers
  - `sample_narratives(suite_dir, *, M=10) -> list[Narrative]`
  - `assess_face_validity(scores, narratives) -> FaceValidityStatus`

- [x] 1.2 单元测试 `tests/test_face_validity.py`：
  - sample_narratives 输出 M=10 + 每 variant ≥ 1
  - assess_face_validity 边界 (avg=3.5 / pct=0.20 临界)
  - Pydantic schema 完整性

## 2. 采样 CLI

- [x] 2.1 `tools/sample_face_validity.py`：
  - 读 suite-dir 下的 trajectories
  - 抽 10 条 narrative；按 variant 分层
  - 输出 narratives.json + prolific_questions.md
  - argparse `--suite-dir` / `--M` / `--output` / `--prolific-template`

## 3. 聚合 CLI

- [x] 3.1 `tools/aggregate_face_validity.py`：
  - 读 Prolific scores CSV (5-col format)
  - 调 assess_face_validity
  - 输出 `data/calibration/face_validity_report.json`
  - argparse `--scores-csv` / `--narratives` / `--output`

## 4. publishable suite report 接入

- [x] 4.1 改 `metrics/report.py::_publishable_checklist`：
  - 读 `data/calibration/face_validity_report.json`
  - checklist #3 状态：✓/✗/⚠️ + 数值 disclose

## 5. 文档

- [x] 5.1 新建 `docs/face_validity/01-protocol.md`：
  - Prolific 招募步骤
  - 题目模板示例
  - scores CSV 格式 spec
  - 重跑触发条件
  - $100 cost 估算

- [x] 5.2 `data/face_validity/.gitignore`：scores CSV 不进 git

## 6. 测试

- [x] 6.1 `tests/test_run_face_validity_cli.py`：
  - sample CLI 输出 schema 正确
  - aggregate CLI 处理样例 scores
  - report.md 含 face validity status

## 7. 验证

- [x] 7.1 全 pytest 通过
- [x] 7.2 `openspec validate face-validity-protocol --strict` 通过

## 8. archive sync

- [x] 8.1 archive 时合 delta spec 入
  `openspec/specs/validation-strategy/spec.md`
- [x] 8.2 commit
