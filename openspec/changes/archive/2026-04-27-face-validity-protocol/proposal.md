## Why

Publishable checklist 最后一项 ✗ —— face validity 是 publishable run 的
**人类回路**门禁：让真人审阅 sim 输出，判断"这是真居民写的吗 / 行为符合
Lane Cove 日常吗"。

`validation-strategy` Part III 规定流程：M=10 条 narrative × N=20 真人
评 5-Likert × 接受阈值 (avg ≥ 3.5/5, ≤ 20% 评 ≤ 2)。

人类流程本身（招募 / 评分采集）在我们 scope 之外（用 Prolific 等平台）。
本 change 实施**两端代码**：
- 入口：narrative 采样 → 输出 Prolific-ready 题目包
- 出口：Prolific 评分 CSV → 聚合 → publishable suite 报告

中间空白由用户填（~$100 + 1-3 天 Prolific 流程）。

**Chain-Position**: `infrastructure`
**前置**：`publishable-finalize`（已 archive，提供 ethics + rep-lock 框架）

## What Changes

### 1. `synthetic_socio_wind_tunnel/metrics/face_validity.py`（新模块）

```python
def sample_narratives(suite_dir: Path, *, M: int = 10) -> list[Narrative]
    """从 suite 跑出的 trajectories 抽 M 条代表性 agent 叙事。
    每 variant 至少 1 条；抽样按 agent.profile 多样性 stratified。"""

def assess_face_validity(scores: list[Score]) -> FaceValidityStatus
    """读取 N 真人评分 → 应用 spec 阈值 → 返回 PASS/FAIL"""
```

`Narrative`：含 `agent_id` / `variant_name` / `summary_text`（agent 14 天
经历的合成 narrative，用 `MemoryService.summarize()` 等已有 helper 生成）。

`Score`：5-Likert 三题（authenticity / lane_cove_realism / least_realistic_segment）。

阈值（spec D Part III）：
- avg ≥ 3.5/5 across all 10 narratives + 20 reviewers = 200 ratings
- ≤ 20% ratings 为 ≤ 2

### 2. `tools/sample_face_validity.py`（采样 CLI）

```bash
python3 tools/sample_face_validity.py \
    --suite-dir data/experiments/<suite> \
    --output data/face_validity/narratives.json \
    --prolific-template data/face_validity/prolific_questions.md
```

输出：
- `narratives.json`：M 条 narrative + 元数据
- `prolific_questions.md`：可上传到 Prolific 的题目模板（含 narrative
  excerpt + 3 题）

### 3. `tools/aggregate_face_validity.py`（聚合 CLI）

```bash
# 假设 user 从 Prolific 下载了 scores CSV：
python3 tools/aggregate_face_validity.py \
    --scores-csv ~/Downloads/prolific_scores.csv \
    --narratives data/face_validity/narratives.json \
    --output data/calibration/face_validity_report.json
```

输出 `face_validity_report.json`：

```json
{
  "generated": "2026-04-30T...",
  "n_narratives": 10,
  "n_reviewers": 20,
  "avg_authenticity": 4.1,
  "avg_realism": 3.8,
  "pct_low_ratings": 0.12,
  "passed": true,
  "details": {...}
}
```

### 4. publishable suite report 接入

`metrics/report.py` 的 checklist 加 #3 检查：
- 报告不存在 → ⚠️ "face validity not run; see tools/sample_face_validity.py"
- 存在但 `passed: false` → ✗ + disclose 原因
- 存在且 `passed: true` → ✓

### 5. `docs/face_validity/01-protocol.md`（新文档）

详细人类流程说明：
- Prolific 招募怎么发布
- 题目模板示例
- scores CSV 格式
- 重跑触发条件（LLM 版本 / PROFILE / prompt template 变更）
- $100 cost 估算

### 6. 测试

- `tests/test_face_validity.py`：
  - sample_narratives 输出 M 条 + 每 variant ≥ 1 条
  - assess_face_validity 边界（avg=3.5 / pct=0.20）
  - JSON schema 完整性
  - aggregate CLI 处理样例 scores CSV

## Non-goals

- **不**自动跑 Prolific（人力流程）
- **不**实现 narrative 自动生成（用 MemoryService 已有 summary）
- **不**替代 stereotype audit（这是独立第二门禁）
- **不**做 narrative LLM 生成质量分析（属下个 change 范围）

## Capabilities

### Modified Capabilities

- `validation-strategy`：Part III Face Validity 实施落地（与 #1/#2 同套
  publishable suite 探测机制）

### New Capabilities

（无）

## Impact

- **修改文件**：
  - `synthetic_socio_wind_tunnel/metrics/report.py`（checklist #3 探测）
- **新增文件**：
  - `synthetic_socio_wind_tunnel/metrics/face_validity.py`
  - `tools/sample_face_validity.py`
  - `tools/aggregate_face_validity.py`
  - `tests/test_face_validity.py`
  - `docs/face_validity/01-protocol.md`
  - `data/face_validity/.gitignore`（narratives + scores 本地保留）
- **不改**：agent / Planner / orchestrator / cartography 公共契约
- **预计周期**：0.5 day（代码部分）+ 1-3 day Prolific 人力（外部）
- **下游影响**：publishable checklist #3 ✗ → 解锁路径
- **回滚**：删两个 CLI + face_validity.py + git revert metrics/report
