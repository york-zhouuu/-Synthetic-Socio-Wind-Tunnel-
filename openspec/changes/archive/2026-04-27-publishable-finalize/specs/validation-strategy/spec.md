## ADDED Requirements

### Requirement: Reproducibility Lock 七字段实施

publishable suite 的每个 RunMetrics SHALL 含以下 7 个 reproducibility
字段（来自 `validation-strategy` Part VI），通过 `RunMetrics.extensions`
机制：

1. `seed_pool: list[int]` — 本次 suite 实际跑过的所有 seed
2. `model_version: str` — `stub:v1` 或 `claude-haiku-4-5-20251001`
   等具体 model id
3. `prompt_template_hash: str` — sha256 of `_PLAN_PROMPT_TEMPLATE`；
   stub 路径下 `"stub:<variant_name>"`
4. `LANE_COVE_PROFILE_hash: str` — sha256 of `LANE_COVE_PROFILE.model_dump_json
   (sort_keys=True)`
5. `variants_loaded: dict[str, str]` — variant_name → sha256 of variant
   config
6. `code_commit: str` — `git rev-parse HEAD`；不可用时 `"unknown"`
7. `phase_config: dict` — `{baseline_days, intervention_days, post_days}`

publishable suite report.md 顶部 SHALL 含 "Reproducibility Lock" section
列出 7 字段；checklist #6 自动判定 ✓ 当七字段全填齐。

#### Scenario: 七字段全填
- **WHEN** publishable suite 跑完后读 RunMetrics.extensions
- **THEN** SHALL 含 seed_pool / model_version / prompt_template_hash /
  LANE_COVE_PROFILE_hash / variants_loaded / code_commit / phase_config
  七个 key；任一缺失 → checklist #6 ⚠️ 而非 ✓

#### Scenario: stub mode prompt_template_hash 标 stub
- **WHEN** suite 跑 `--mode dev` (stub-only)
- **THEN** prompt_template_hash SHALL == `"stub:<variant_name>"` per variant；
  非 sha256 hex string

#### Scenario: git 不可用 fallback
- **WHEN** subprocess `git rev-parse HEAD` 抛 OSError 或 CalledProcessError
- **THEN** code_commit SHALL == `"unknown"`；其它字段不受影响


### Requirement: Ethics Statement 自动注入

publishable suite report.md SHALL 在生成时自动注入 `Research Posture
Statement` 段落（来自 `validation-strategy` Part V via
`research-design` Part V），无需作者手填。

ethics 文本 SHALL 作为模块常量存
`synthetic_socio_wind_tunnel/metrics/ethics.py`，**单一来源**——
report.md / docs 引用同一常量，避免漂移。

#### Scenario: report.md 含 ethics
- **WHEN** publishable suite 跑完产出 report.md
- **THEN** report.md SHALL 含 `## Research Posture Statement` heading +
  完整 ethics 段；checklist #7 自动判定 ✓

#### Scenario: ethics 常量可 import
- **WHEN** 调用 `from synthetic_socio_wind_tunnel.metrics.ethics import
  ETHICS_STATEMENT`
- **THEN** 返回 str；含关键短语 "云室" 和 "dual-use"
  （research-design Part V 一致性 anchor）
