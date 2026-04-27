# Face Validity Protocol — Lane Cove

`validation-strategy` Part III 的人类回路：让真人审阅 sim 输出的 agent 叙事，
判断"这是否像真实 Lane Cove 居民"。

## 流程概览

```
[1] sample_face_validity.py  → narratives.json + prolific_questions.md
                                       ↓
[2] 上传 Prolific（或同等众包平台）
                                       ↓
[3] 招募 N=20 reviewer, 5-7 minutes / reviewer × $5 ≈ $100
                                       ↓
[4] 下载 scores CSV
                                       ↓
[5] aggregate_face_validity.py → face_validity_report.json
                                       ↓
[6] publishable suite report 自动 checklist #3 ✓/✗
```

## 步骤 1: 采样 narratives

```bash
python3 tools/sample_face_validity.py \\
    --variants baseline,hyperlocal_push,global_distraction,shared_anchor \\
    --M 10 \\
    --seed 42
```

输出：
- `data/face_validity/narratives.json` —— 10 条 narrative 元数据
- `data/face_validity/prolific_questions.md` —— Prolific 上传模板

## 步骤 2-3: Prolific 招募与答题

### 平台选择

- **Prolific**（推荐）：academic-friendly, geo-filtering 可优先 Sydney
  resident
- **Mechanical Turk**：备选；过滤严格度更低
- **本地众包**（如校园招募）：免费但样本小

### 招募 spec（per validation-strategy Part III）

- **N = 20** 真人 reviewer（spec 最低）
- **优先 Lane Cove / Sydney resident**（geo filter）
- 每人评 10 条 = 200 ratings 总数
- 每人 5-7 分钟 → $5 / reviewer ≈ **$100 total**

### 题目结构（每 narrative 3 题）

1. **Q1 Authenticity**（1-5 Likert）：像真实居民写的吗？
2. **Q2 Realism**（1-5 Likert）：行为符合 Lane Cove 日常吗？
3. **Q3 Free text**（可选）：最不像的一段是哪段？为什么？

### 上传 Prolific 流程

1. 复制 `prolific_questions.md` 到 Prolific 的 Survey Builder
2. 配置：
   - Eligibility: location = Sydney/NSW（best-effort）
   - Reward: $5
   - Estimated time: 7 minutes
3. 发布；等 1-3 天 reviewer 完成

### scores CSV 格式

下载的 CSV 需要 5 列：

```csv
reviewer_id,narrative_id,q1_authenticity,q2_realism,q3_text
prolific_001,narrative_00,4,5,
prolific_001,narrative_01,3,3,"3am library visit feels off"
...
```

如果 Prolific 默认导出格式不一致，可手工转换或写小 script wrap。

## 步骤 5: 聚合

```bash
python3 tools/aggregate_face_validity.py \\
    --scores-csv ~/Downloads/prolific_scores.csv
```

输出 `data/calibration/face_validity_report.json`：

```jsonc
{
  "passed": true,
  "overall_avg": 3.91,
  "pct_low": 0.145,
  "n_narratives": 10,
  "n_reviewers": 20,
  "details": {...}
}
```

## Acceptance 阈值

每 publishable run 必须**两个条件都满足**：

- **Overall average rating ≥ 3.5/5**（authenticity + realism 平均）
- **≤ 20% ratings 评 ≤ 2**（即至少 80% reviewer-narrative pair 给 3+）

## 重跑触发条件

按 spec Part III，下列变化必须重跑：

- LLM 版本变化（如换模型）
- `LANE_COVE_PROFILE` 变化
- Planner prompt template 变化
- agent 13 维 enrich 字段值变化（即 ABS data refresh）

每个 publishable suite **必跑一次**。

## 成本

- 每次 face validity 跑：~$100 Prolific budget
- 每次需要 1-3 天 wall clock（reviewer 完成 + 数据下载）

## 故障排查

**Q: scores CSV 解析失败**
A: 检查列名匹配。可手动重命名 columns 后重跑。

**Q: 某些 reviewer 给全 1 或全 5（懒答）**
A: spec 不要求过滤；保留所有数据 + 在 publishable artifact disclose
  reviewer 评分分布（histogram）。

**Q: 招到的 reviewer 不熟 Lane Cove**
A: 接受 best-effort；在题目 brief 里附 1-page Lane Cove 简介帮 reviewer
  建立 reference frame。

**Q: 想用 LLM 模拟 reviewer（节约成本）**
A: 不行——face validity 的全部价值在于"真人审"。LLM-only audit 会被
  reviewer 抓住论文里说"我们用 LLM 审 LLM 输出"。
