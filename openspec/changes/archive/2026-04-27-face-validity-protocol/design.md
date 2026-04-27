## Context

最后一项 publishable 门禁。Face validity 是人类回路 — 真人评 sim 输出 → 我们
读评分 → 算 acceptance。

## Goals / Non-Goals

**Goals**：
- 入口端代码：narrative 采样 + Prolific 题目模板生成
- 出口端代码：Prolific scores 聚合 + acceptance 判定
- publishable suite report 自动 checklist #3 状态
- 文档：人类流程清晰可重跑

**Non-Goals**：
- 不实现自动 Prolific 招募（外部 SaaS）
- 不做 narrative LLM 生成（用 MemoryService 已有 summary）
- 不做评分质量分析（多评分员一致性、reviewer drift 等）

## Decisions

### D1：narrative 来源

**选择**：从 suite-dir 里的 trajectory data + MemoryService.summary 抽样。

**Why**：sim 已经跑出来 trajectories（`seed_*.json` 含 daily summaries），
MemoryService 有 daily_summary helper。M=10 narrative 抽样：
- 每 variant ≥ 1（保证 narrative 多样性）
- 用 agent.profile 维度 stratified（gender / community_tenure / 等）
- 每条取 3-day excerpt + agent profile context

### D2：Prolific 题目模板

3 题（spec Part III）：
1. **Authenticity**: "这段叙事像真实居民写的吗？" 1-5 Likert
2. **Realism**: "行为符合 Lane Cove 日常吗？" 1-5
3. **Free-text**: "最不像的一段是哪段？为什么？"（可选）

输出 markdown 模板可直接复制粘贴到 Prolific：

```markdown
# Lane Cove Resident Narrative — Reviewer Survey

You are reviewing 10 anonymized 3-day narratives. For each:

## Narrative 1
> {summary_text}

**Q1**: How likely is this written by a real Lane Cove resident? (1=very unlikely, 5=very likely)
**Q2**: How well does this match daily life in Lane Cove?...
**Q3** (optional)...
```

### D3：scores CSV format

**选择**：3-column wide format per reviewer-narrative pair：
```
reviewer_id, narrative_id, q1_authenticity, q2_realism, q3_text
prolific_001, narrative_03, 4, 5, ""
prolific_001, narrative_07, 2, 3, "agent went to library at 3am"
...
```

10 narratives × 20 reviewers = 200 rows. CSV is portable + Prolific
exports CSV natively.

### D4：acceptance 判定

```python
def assess_face_validity(scores: list[Score]) -> FaceValidityStatus:
    avg_q1 = mean(s.authenticity for s in scores)
    avg_q2 = mean(s.realism for s in scores)
    overall_avg = (avg_q1 + avg_q2) / 2
    pct_low = sum(1 for s in scores if min(s.authenticity, s.realism) <= 2) / len(scores)
    
    passed = (overall_avg >= 3.5) and (pct_low <= 0.20)
    return FaceValidityStatus(passed=passed, ...)
```

**Why both Q1+Q2 averaged**: Spec says "M=10 平均得分 ≥ 3.5/5"——单个题
平均不够；两题都要过。

### D5：data/face_validity 目录结构

```
data/face_validity/
  .gitignore       # exclude raw scores CSV (PII-adjacent)
  narratives.json  # commit (auditable)
  prolific_questions.md  # commit
```

scores CSV 不进 git（含 reviewer_id 等可能 PII-ish 字段）。

### D6：publishable suite report 接入

通过现有 `metrics/report.py::_publishable_checklist` 扩展，与 calibration
+ stereotype audit 同模式：

```python
fv = _read_optional_json(repo_root / "data" / "calibration" / "face_validity_report.json")
if fv is None:
    lines.append("- ⚠️ **#3 Face validity**: not run; see docs/face_validity/01-protocol.md")
elif fv.get("passed"):
    lines.append(f"- ✓ **#3 Face validity**: avg={fv['overall_avg']:.2f}, pct_low={fv['pct_low']:.1%}")
else:
    lines.append(f"- ✗ **#3 Face validity**: avg={fv.get('overall_avg', '?')}, pct_low={fv.get('pct_low', '?')}")
```

## Risks / Trade-offs

**[Risk 1] Prolific 招募 ≠ Lane Cove resident**
→ 文档写明"优先 Sydney resident"；接受 best-effort（地理筛选 SaaS 不一定
  完全严格）；disclose in narrative_report

**[Risk 2] 文化偏差 reviewer 不熟 Lane Cove**
→ 题目附 1-page Lane Cove 简介（人口结构 + 主要 POI）作 brief

**[Risk 3] 200 ratings 样本量小**
→ spec 数；sufficient for face validity（不是 stat power test）

**[Risk 4] Narrative 太短/太长**
→ M=10 → 每条限 200-300 词（Prolific reader 体力）；多 day 才能 capture
  agent 行为 → 3-day excerpt

**[Risk 5] reviewer drift（早期 evaluator 严格、后期宽松）**
→ 不修复（spec 不要求）；CSV 留 timestamps 让 reviewer 单独看

## Migration Plan

1. 新建 `metrics/face_validity.py`：narrative model + assess function
2. 新建 `tools/sample_face_validity.py`
3. 新建 `tools/aggregate_face_validity.py`
4. `metrics/report.py::_publishable_checklist` 加 #3 探测
5. 文档 `docs/face_validity/01-protocol.md`
6. 测试 + 全 pytest
7. archive sync

**回滚**：删 face_validity 模块 + 两个 CLI + git revert report.py

## Open Questions

1. **Q1**: narrative excerpt 用 MemoryService.summary 还是手工拼？
   倾向：用 summary（avoids LLM cost；已 validated by memory change）

2. **Q2**: reviewer 是否每人都看 10 条，还是 stratified？
   倾向：每人看 10 条（spec 200 ratings = 20×10）；保留 wholeness

3. **Q3**: $100 budget 触发条件？
   倾向：每 publishable suite 跑一次；LLM 版本变化必重跑（spec 已规定）
