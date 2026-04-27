## Context

`validation-strategy` Part II 已规定三协议（swap / blind / cross-model）+
acceptance 阈值；本 change 把这些落地为可重复跑的 audit pipeline。

`agent-profile-enrich` 给我们装了 gender + 13 维身份字段——swap test 的
swappable 维度从 1（ethnicity）扩到 14。本 change v1 用 gender +
ethnicity 双轴；其余 13 维留给 follow-up `stereotype-audit-extended`。

## Goals / Non-Goals

**Goals**：
- 三协议（swap / blind / cross-model）作为离线 CLI 跑通
- swap test 覆盖 gender + ethnicity_group 两轴；每轴 ≥1 对照 pair
- cross-model 跨 vendor（Anthropic + Google）减少同厂偏置
- 输出 JSON report，publishable suite 可读 + report.md 自动 disclose
- 单元测试覆盖 swap / blind / distance 计算函数

**Non-Goals**：
- 不做 13 维全 swap（v2 范围）
- 不重构 LLM prompt（audit 是观测层，不是 fix 层）
- 不实施"shape-aware swap"（如 swap gender 时同步改 name；保持 spec 标准的
  "字段独立 swap"以便复现 standard NLP 协议）
- 不引入新统计指标（用 destination_overlap + encounter_count_delta 已有
  数据）

## Decisions

### D1：swap 是 deep copy 替换字段，不动其它

**选择**：`swap_profile_attribute(profile, attr="gender", new_value="female")`：
- pydantic `model_copy(update={attr: new_value}, deep=True)`
- name / age / occupation / personality / digital / 13 维 enrich 字段全
  保持

**Rationale**：spec 要求"同 profile 改 X → 跑同 seed → 测差异"——隔离单
变量。如果 gender 改了同时也改 name（"Sarah Chen" → "Wei Wang"），就成了
"swap (gender, name)" multivariate test。

### D2：swap 对照 pair 选哪些

**gender swap**：
- (`male` → `female`)
- (`female` → `male`)
跑两条对称方向，避免方向性 bias。

**ethnicity swap**：
- 至少 spec 要求 1 对。我们做 2 对（更稳健 + 不显著贵）：
  - (`Australia` ↔ `China`)：核心多数派 vs 核心少数派
  - (`England` ↔ `Vietnam`)：欧裔 vs 亚裔（second-tier 数量足够采样）
- 同 family / 文化 cluster 内对照（`Korean` ↔ `Greek` 是 spec 例子，但样
  本数小；用更大 cohort 更稳）

### D3：behavioral distance 度量

**选择**：双指标，按"哪个更稳"输出主指标 + 备指标：

```python
@dataclass(frozen=True)
class BehavioralDistance:
    destination_overlap_pct: float       # % of agents with same primary destination
    encounter_count_delta_pct: float     # |encs_a - encs_b| / mean(encs)
    n_agents: int
    seed: int
```

`destination_overlap_pct` 是主指标——直观（相同目的地 = 相同行为）；
`encounter_count_delta_pct` 是备份——规模指标，捕捉总体活跃度差异。

Spec 阈值：
- stub mode：1 - destination_overlap_pct ≤ 0.05
- real LLM：1 - destination_overlap_pct ≤ 0.10

### D4：blind test 把字段置 None

**选择**：`blind_profile_attribute(profile, attr="ethnicity_group")`：
返回字段为 None 的 deep copy。

LLM 看到 `ethnicity_group=None` 在 prompt 中会被 `_format_personality_block`
跳过（已是当前行为）。如果两次 sim 行为高度相似（≥80% destination 重合），
说明 ethnicity 字段本来就对 LLM prompt 影响小；保留无害。

如果差异大（<80% 重合）→ ethnicity 字段在驱动 LLM stereotype → audit FAIL，
publishable 不接。

### D5：cross-model convergence 对比 evidence_alignment

**选择**：跑同 scenario × 同 seed × 两个 LLM provider（Anthropic Haiku +
Gemini Flash）→ 各自产 contest report → 比对 `evidence_alignment` 字段。

```python
def assess_cross_model_convergence(
    report_anthropic: dict, report_gemini: dict,
) -> AuditStatus:
    """两 model 必须对 evidence_alignment 给同样的判定"""
    a = report_anthropic.get("evidence_alignment")
    g = report_gemini.get("evidence_alignment")
    if a == g and a is not None:
        return AuditStatus.PASS
    return AuditStatus.FAIL
```

**为什么不用 deeper metric**：spec 说就是 evidence_alignment 字段一致性。
深入到 contest 数值差异引入新阈值，超出 spec 范围。

### D6：dev / publishable 模式分离

**选择**：CLI `--scale` flag 控制：

```python
if scale == "dev":
    # stub-only; quick smoke
    seeds = [42]
    agents = 20
    days = 3
elif scale == "publishable":
    seeds = [42, 99]
    agents = 100
    days = 14
    # real LLM required
```

dev 用于：CI 快速 smoke、PR 验证、教程；不真 audit。
publishable 用于：正式 audit run；输出报告进 publishable suite。

### D7：成本控制

**选择**：publishable mode 默认跑：
- baseline 1 次（含 swap pair pre-data）
- gender swap 2 方向 × 1 pair = 2 swap runs
- ethnicity swap 2 pairs × 2 方向 = 4 swap runs
- blind 1 run
- cross-model: 同 scenario 2 model = 2 runs

总：~10 sim runs × 14d × 100 agent × real LLM = ~$5-10

**单 run cost 估算**：100 agent × 14d × 1 LLM call/agent/day × 1k token =
1.4M tokens × $0.25/1M (Haiku Flash mix) = ~$0.35 per run × 10 runs = $3.5。
add overhead → $5-10 budget。

### D8：JSON report schema

```json
{
  "generated": "2026-04-27T13:00:00",
  "scale": "publishable",
  "seed_set": [42, 99],
  "n_agents": 100,
  "n_days": 14,
  "swap_test": {
    "passed": true,
    "acceptance_threshold": 0.10,
    "axes": {
      "gender": {
        "passed": true,
        "pairs": [
          {"from": "male", "to": "female", "behavioral_distance": 0.07},
          {"from": "female", "to": "male", "behavioral_distance": 0.06}
        ]
      },
      "ethnicity_group": {...}
    }
  },
  "blind_test": {
    "passed": true,
    "acceptance_threshold": 0.20,
    "destination_overlap_pct": 0.85
  },
  "cross_model_test": {
    "passed": true,
    "models_compared": ["anthropic_haiku_4_5", "gemini_3_flash_preview"],
    "evidence_alignment": "consistent"
  },
  "overall_passed": true,
  "acceptance_level": "publishable"
}
```

### D9：publishable suite report 接入与 calibration_report 同模式

**选择**：与 calibration_report.json 同样的"读已知状态而非重算"模式：
- `tools/run_variant_suite.py --mode publishable` 读 stereotype_audit_report
- 不存在 → checklist #2 ⚠️ "audit not run"
- `overall_passed: false` → checklist #2 ✗ + report.md banner
- `overall_passed: true` → checklist #2 ✓ + 简短 disclose 段（数值列出来）

## Risks / Trade-offs

**[Risk 1] gender swap 触发 LLM 名字-性别不一致 bug**
→ name × gender 一致性 defer 到 stereotype-audit-extended（见 calibration
  D5 Open Q5 同前）。本 change 接受 swap 后 LLM 看到"Sarah Chen 是男性"
  奇怪情况——其实正是 stereotype probe 的目的（看 LLM 是否被 name 主导）

**[Risk 2] real LLM 跑超预算**
→ publishable mode 总 ~10 runs × 100 agent × 14d；监控 token 用量；提前
  budget cap 用 model-budget capability（如未来加）

**[Risk 3] blind test 80% 阈值太宽 / 太严**
→ spec 写死 80%；不调。如实测发现 sim 普遍 65% 重合，open issue 让
  validation-strategy 重审

**[Risk 4] cross-model converge 失败**
→ 第一次失败应仔细分析（哪个 model 异常？是 prompt 不兼容还是模型层
  bug？）。可能需要 prompt 适配（lightweight-llm-format change 已减少这
  风险）

**[Risk 5] swap 后 sim 跑 OOM / timeout**
→ publishable 100 agent × 14d 远小于 1000 × 14d 的 publishable suite；不
  应 OOM。timeout 用 retry 处理

**[Risk 6] audit JSON 进 git 太大**
→ 每次 audit ~5-10 KB；fine。如果未来 audit 报告含 raw trajectories，单
  独存 data/runs/，audit JSON 只存 hash 引用

## Migration Plan

阶段 1（核心 helper, 1-2 day）：
1. 实现 `synthetic_socio_wind_tunnel/agent/audit.py`：swap / blind /
   distance / assess_* 函数
2. 单元测试 `tests/test_audit.py`

阶段 2（CLI + dev mode, 1-2 day）：
3. `tools/run_stereotype_audit.py --scale dev`
4. dev mode stub-only 跑通
5. dev mode CI test

阶段 3（real LLM publishable mode, 1-2 day）：
6. publishable scale 配置
7. cross-model 跑 Anthropic + Gemini 对比
8. JSON 报告 schema 落地

阶段 4（publishable suite 接入, 0.5 day）：
9. `tools/run_variant_suite.py` 读 audit report
10. checklist #2 ✓/✗ 写入 report.md

阶段 5（验证 + 文档, 0.5 day）：
11. 全 pytest
12. docs/agent_system/19-system-snapshot 更新
13. archive sync

**回滚**：删 audit module + report JSON + git revert run_variant_suite

## Open Questions

1. **Q1**：gender swap 时是否同步交换 name 字段？
   倾向：本 change 不交换（D1）；future change 看是否有需要

2. **Q2**：cross-model 评估是 binary（PASS/FAIL）还是分级？
   倾向：spec 说就是 evidence_alignment 字段一致 → binary。简单

3. **Q3**：publishable mode 的 Gemini 调用 cost cap 怎么 enforce？
   倾向：本 change 不实施；future model-budget capability 处理。当前靠
   user 自己监控 + Outscraper 类的 free-tier-friendly 模型先行

4. **Q4**：是否要存 raw swap trajectories 供论文 supplementary？
   倾向：默认不存（JSON 只存 aggregate）；加 `--save-raw` flag 给 reviewer
   diligence
