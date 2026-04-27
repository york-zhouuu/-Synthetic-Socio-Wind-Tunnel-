## Why

`validation-strategy` (2026-04-25) 第 II 部分定义了三个 stereotype audit 协议
（swap / blind / cross-model）作为 publishable checklist 第 2 项的硬门禁。
当前状态 ✗——三协议都未跑过。

stereotype audit 直击 LLM agent 的最大研究风险：**LLM 是否在按身份字段
（性别 / 族裔）刻板地输出行为，而不是在模拟真实居民？**

如果 audit FAIL：
- 同 profile 改 ethnicity 行为变化巨大 → LLM 在按族群 stereotype 生成 plan
- 删 ethnicity 后行为变化巨大 → ethnicity 字段在主导 prompt
- 不同 model（Anthropic vs Google）给出不同 evidence_alignment 判定 → 模型层不稳定

任一发生 → publishable run 报告 `[unpublishable preview]` 顶部 banner，
"我们做的不是 sim，是 LLM 在演戏"。

agent-profile-enrich (2026-04-27) 给我们装了 13 维身份字段，**正好为 swap
test 备好了多轴**。本 change 把这三协议落地为可重复跑的 audit pipeline。

**Chain-Position**: `infrastructure`（不动 thesis 主链；只加 audit 探针 +
报告生成）

**前置**：
- `agent-calibration` (best-effort 5/6) — LANE_COVE_PROFILE 已校准
- `agent-profile-enrich` — gender + 13 维身份字段已加；为 swap test 提供
  必需的 swappable 维度

## What Changes

### 1. `synthetic_socio_wind_tunnel/agent/audit.py`（新模块）

提供三个 swap / blind / cross-model 的纯函数 helper：

- `swap_profile_attribute(profile, attr, new_value) → AgentProfile`
  返回 deep copy 的 profile 但替换指定字段；其它字段（含人格 / 数字习惯）
  完全保持
- `blind_profile_attribute(profile, attr) → AgentProfile`
  返回 deep copy 把指定字段置 None
- `compute_behavioral_distance(run_a, run_b) → BehavioralDistance`
  对比两次 sim run 的 destination overlap + encounter count delta
- `assess_swap_acceptance(distance, mode="stub"|"real_llm") → AuditStatus`
  按 spec 阈值（stub ≤5%, real ≤10%）裁定
- `assess_blind_acceptance(distance) → AuditStatus`
  阈值：≥80% seed 重合
- `assess_cross_model_convergence(reports_a, reports_b) → AuditStatus`
  对比两个 model 的 contest evidence_alignment 字段

### 2. `tools/run_stereotype_audit.py`（新 CLI）

跑三协议，输出 `data/calibration/stereotype_audit_report.json`。

```bash
python3 tools/run_stereotype_audit.py --scale dev      # stub-only, ~30s
python3 tools/run_stereotype_audit.py --scale publishable --use-real-llm \
    --llm-provider gemini  # real LLM, 14d×100 agent×2 seed
```

CLI 内部：
- 跑 baseline run（无 swap）
- 对每个 swap pair：clone profile + swap → 跑同 seed run → 算
  behavioral_distance
- blind: 全 1000 agent 删 ethnicity_group → 同 seed run → 算 distance
- cross_model: 第二个 LLM provider 跑同 scenario → 比 contest output

### 3. Swap 双轴：gender + ethnicity_group

**v1 做**（按 spec 最低要求 + NLP 标配）：
- **gender**：male ↔ female swap（NLP stereotype 经典轴）
- **ethnicity_group**：Han Chinese ↔ Anglo-Australian / Korean ↔ Greek
  （spec 要求 ≥1 对）

**v1 不做**（defer 到下个 change）：
- family_composition / community_tenure / volunteer_status 等 13 维 swap
- 13 维 swap 价值大但工时翻倍；先把 spec 必修跑通

### 4. Cross-model 跨 vendor

**Anthropic Haiku** + **Gemini Flash**——跨厂商收敛比同厂内部强：

- 同厂家两个 model 可能共享 RLHF bias；跨厂收敛排除"恰好两 model 都被
  同样训出"的 alternative explanation
- Gemini client 已 wired (`tools/suite_stub_llm.py::_GeminiClient`)
- Haiku 是当前默认 base_model

### 5. 规模：dev mode + publishable mode

| Mode | seed × agent × day | 耗时 (real LLM) | 用途 |
|---|---|---|---|
| `dev` | 1 × 20 × 3 (stub) | ~10 s | smoke / unit test |
| `publishable` | 2 × 100 × 14 | ~30 min × $5-10 | 真 publishable 报告 |

**不**跑 1000 × 14d 全规模——成本翻 10 倍，对 audit 信号无质变。

### 6. publishable suite report 接入

`tools/run_variant_suite.py --mode publishable` 读
`data/calibration/stereotype_audit_report.json`：
- 三协议 PASS → checklist #2 ✓
- 任一 FAIL → ✗ + report.md 顶部 `[unpublishable preview]` banner +
  详细 disclosure 段（哪个协议哪个轴 fail，距离多少）
- report 不存在 → ⚠️ "stereotype audit not run"

### 7. 测试

- `tests/test_audit.py`：
  - swap_profile / blind_profile 函数 round-trip 正确性
  - compute_behavioral_distance 对手造数据的数值正确
  - assess_*_acceptance 边界条件
- `tests/test_run_stereotype_audit.py`：
  - dev mode 跑通 + 输出 schema 正确
  - 三协议各自的 report 字段都存在

## Non-goals

- **不**做 face-validity-protocol（Prolific 人力流程，独立 change）
- **不**改 LLM prompt（audit 只观察 LLM 输出的 invariance）
- **不**改 PlanStep / DailyPlan / AgentRuntime 公共契约
- **不**做 13 维全 swap（gender + ethnicity_group 已够 spec；13 维 swap
  下个 `stereotype-audit-extended` change 做）
- **不**自动修复 audit FAIL（FAIL → 报告 disclose；fix 是工程师的事）
- **不**实施"跨 model 评分"指标融合（保持 evidence_alignment 字段比对，
  不引入新指标）

## Capabilities

### Modified Capabilities

- `agent`：新增 audit 模块要求 + swap / blind 函数 SHALL 不破坏 profile
  其它字段
- `validation-strategy`：把 Part II 三协议从 doc 提升到 spec scenario，加
  publishable suite report 探测 hook（与 Part IV/V calibration 报告同套
  机制）

### New Capabilities

（无）

## Impact

- **修改文件**：
  - `synthetic_socio_wind_tunnel/agent/__init__.py`（新模块 export）
  - `tools/run_variant_suite.py`（report 接入）
- **新增文件**：
  - `synthetic_socio_wind_tunnel/agent/audit.py`
  - `tools/run_stereotype_audit.py`
  - `tests/test_audit.py`
  - `tests/test_run_stereotype_audit.py`
  - `data/calibration/stereotype_audit_report.json`（生成产物，可入 git
    供 reviewer 审阅）
- **不改**：
  - LLM prompt template / Planner / AgentRuntime 公共契约
  - attention chain / orchestrator / metrics
  - Atlas / cartography
- **新增依赖**：无（重用 numpy / scipy from agent-calibration）
- **下游影响**：
  - publishable checklist #2 ✗ → ✓
  - face-validity-protocol 解锁（face-validity 依赖 audit 通过的 sim 输出）
- **预计周期**：1 周（含 dev/publishable mode 实施 + 真 LLM smoke）
- **回滚**：删 audit.py / run_stereotype_audit.py + git revert + 删 JSON
- **成本**：publishable mode 跑一次 ~$5-10（Haiku + Gemini Flash mix）
