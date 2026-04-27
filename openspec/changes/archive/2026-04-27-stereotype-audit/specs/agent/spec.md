## ADDED Requirements

### Requirement: stereotype audit module 提供 swap / blind / distance helpers

`synthetic_socio_wind_tunnel/agent/audit.py` SHALL 提供以下纯函数 helpers，
独立于 sim runtime（不被 hot path 调用）：

1. `swap_profile_attribute(profile: AgentProfile, attr: str, new_value) -> AgentProfile`
2. `blind_profile_attribute(profile: AgentProfile, attr: str) -> AgentProfile`
3. `compute_behavioral_distance(run_a, run_b) -> BehavioralDistance`
4. `assess_swap_acceptance(distance, *, mode: Literal["stub","real_llm"]) -> AuditStatus`
5. `assess_blind_acceptance(distance) -> AuditStatus`
6. `assess_cross_model_convergence(report_a: dict, report_b: dict) -> AuditStatus`

设计意图（见 `stereotype-audit` change design D1-D6）：把 validation-strategy
Part II 三协议从 doc 提升为可重复跑的 audit pipeline，作为 publishable
checklist #2 的硬门禁实施。

具体要求：

1. `swap_profile_attribute` SHALL 用 `profile.model_copy(update={attr: new_value}, deep=True)`
   返回新 profile；其它字段（name / personality / digital / 13 维 enrich
   字段）MUST NOT 改变
2. `blind_profile_attribute` SHALL 把指定字段置 None；其它字段保持
3. audit 模块 MUST NOT 被 `runtime.py` / `planner.py` / orchestrator hot
   path import；只被 `tools/run_stereotype_audit.py` 调用

#### Scenario: swap 隔离单变量
- **WHEN** 调用 `swap_profile_attribute(profile, attr="gender", new_value="female")`
  且 profile.gender 原为 "male"
- **THEN** 返回新 profile.gender == "female"；name / age / personality /
  housing_tenure / 13 enrich 字段 SHALL 与原 profile 完全一致

#### Scenario: blind 把字段置 None
- **WHEN** 调用 `blind_profile_attribute(profile, attr="ethnicity_group")`
  且 profile.ethnicity_group 原为 "China"
- **THEN** 返回新 profile.ethnicity_group is None；其它字段保持

#### Scenario: hot path 不导入 audit
- **WHEN** 检查 runtime.py / planner.py / orchestrator import 列表
- **THEN** 都 SHALL NOT 含 `from .audit import` 或 `import synthetic_socio_wind_tunnel.agent.audit`


### Requirement: stereotype audit CLI 单一入口

`tools/run_stereotype_audit.py` SHALL 是跑三协议的唯一 CLI 入口；输出
`data/calibration/stereotype_audit_report.json`。

CLI 接受 `--scale {dev|publishable}` flag：
- `dev`：stub-only，1 seed × 20 agent × 3 day（~10 s）；用于 CI / smoke
- `publishable`：要求 `--use-real-llm`，2 seed × 100 agent × 14 day
  （~30 min × $5-10）；用于真 publishable 报告

#### Scenario: dev mode stub-only
- **WHEN** `python3 tools/run_stereotype_audit.py --scale dev`
- **THEN** 不需 API key；执行时间 < 30 s；输出 JSON 含 swap_test /
  blind_test 段；cross_model_test SHALL 标 `state: "skipped (stub mode)"`

#### Scenario: publishable mode 要求 real LLM
- **WHEN** `python3 tools/run_stereotype_audit.py --scale publishable`
  无 `--use-real-llm`
- **THEN** SHALL sys.exit(2) + 诊断 message："publishable scale requires
  --use-real-llm"


### Requirement: audit report JSON schema

`data/calibration/stereotype_audit_report.json` SHALL 含以下顶层字段：

- `generated`：ISO 时间戳
- `scale`：`"dev"` 或 `"publishable"`
- `swap_test`：含 `passed: bool`、`axes: dict[axis_name → AxisResult]`
- `blind_test`：含 `passed: bool`、`destination_overlap_pct: float`
- `cross_model_test`：含 `passed: bool`、`models_compared: list[str]`、
  `evidence_alignment` 字段比对结果
- `overall_passed`：三协议全 pass 时 true

#### Scenario: report schema 完整
- **WHEN** publishable mode 跑完后读 stereotype_audit_report.json
- **THEN** 顶层 SHALL 含 generated / scale / swap_test / blind_test /
  cross_model_test / overall_passed 6 个字段；每个 *_test 子字段含
  passed: bool

#### Scenario: dev mode cross_model 标 skipped
- **WHEN** dev mode 跑完
- **THEN** report.cross_model_test.state SHALL == "skipped (stub mode)"；
  overall_passed SHALL 仍能基于其它两协议判定（dev mode 时 disclose
  cross_model 未跑）
