# Design — thesis-focus

## 决策 1：保留"机制链"而不是只留"单一边界"

**问题**：既然 attention 是主边界，是否应该直接删掉其它三条，只谈
attention？

**决策**：不能。保留四层，但给出链条方向（一主三机制）。

**原因**：
1. 纯 attention 研究没有空间维度——退化为 UX / HCI 研究，失去城市研究
   本色，与"社会设计 / 计算社会科学 / 交互系统设计"的三重定位不符。
2. 没有 `social-downstream` 就没法闭环 thesis：推送改变了轨迹 → 然后呢？
   没有社交转化的证据，thesis 只证到一半（注意力 → 空间），缺后半
   （空间 → 社交）。
3. `algorithmic-input` 是 `policy-hack` 存在的合法性来源：没有"feed 算法
   偏全球而非 hyperlocal"这个前提，就不需要"反向推送"这种干预。删掉它
   会让 policy-hack 悬空。

结论：**保留四层结构，但从"平列四重边界"改为"一主三机制链"**——每层
都有确定的位置和职责，不再是并列物。

## 决策 2：canonical thesis 文件放哪里

**候选**：
- A. `docs/THESIS.md`（顶层专门一个）
- B. `docs/agent_system/00-thesis.md`（与其它设计文档同置，编号靠前）
- C. `openspec/thesis.md`（与 openspec 规格同置）

**决策**：**B**。

**原因**：
- `docs/agent_system/` 已是设计文档事实位置（01~11 自成体系），加 00
  表示"先读此文件"
- 顶层放 THESIS.md 与 README 重复——README 本身就承担一部分 thesis
  陈述职责
- 放 openspec 会让 openspec 承担非契约的内容（openspec 是契约 + change
  proposal，不是叙事文档）

## 决策 3：Chain-Position 门禁的形式

**候选**：
- A. 改 `openspec/config.yaml` 加 linter 规则，review 前 machine-check
- B. 改 `phase-2-roadmap/tasks.md` 的前置说明，review 时人工 check
- C. 两者都做

**决策**：**B**。

**原因**：
- 现有 fitness-report 引用门禁也只在 tasks.md 的 blurb 里，没有
  machine-checked linter——保持一致
- 门禁是 review-time contract，不是 build-time check
- 过早引入 linter 会让 openspec 文件格式僵化，之后迭代成本变高
- 未来如果门禁被违反多次，再规范化也来得及

## 决策 4：Brief v1 的"四重边界"如何处置

**候选**：
- A. 直接改写，v1 原文删除
- B. 保留 v1 原文作为"开题期表述"的历史附录，v2 收敛写在前面
- C. 把 v1 四重边界完全替换

**决策**：**B**。

**原因**：
- v1 Brief 有历史价值——它记录了项目的起点概念撒网，便于日后回顾 thesis
  是如何收敛的（研究过程本身也是一种产出）
- 直接删除会让答辩时"为什么改变"没有证据链
- 附录形式清晰分隔 v1 / v2，避免读者把两者混读

## 决策 5：原 Brief "产品化想象"条目（政策制定接口 / 参与式设计 /
反哺现实）如何处置

**候选**：
- A. 删除
- B. 降级到 "若 thesis 得到验证，产品化方向是……" 的外溢章节
- C. 保留为非常接近的目标

**决策**：**B**。

**原因**：这类条目属于"如果 thesis 验证成立，这套工具可以怎么用"，
不是研究本身。明确标记为"外溢（spill-over）"或"产品想象（product
imagination）"，避免与研究范围混淆，也避免 reviewer 把这些当成要
交付的内容来 gate。

## 决策 6：Chain-Position 枚举值如何取名

**候选**：
- A. 中文：`算法输入 / 注意力主线 / 空间产出 / 社交下游`
- B. 英文：`algorithmic-input / attention-main / spatial-output / social-downstream`
- C. 混合

**决策**：**B（英文 kebab-case）**。

**原因**：
- 与 `openspec` 全局命名约定（能力名、change 名都是 kebab-case）一致
- 便于未来做 machine-check 时直接字符串匹配
- 英文术语在学术讨论中也更易对外交流

## 决策 7：是否给现有已归档 change 回填 Chain-Position

**决策**：**不回填**。

**原因**：
- 归档 change 是历史记录，不应再被修改
- Chain-Position 是**开工前**的门禁，不是事后分类学
- 新门禁只约束未来 change，不需要溯及既往

## 风险

### 风险 1：文档 drift
canonical 文件（00-thesis.md）更新了，其它文档未同步。

**缓解**：
- 其它文档**只写一句话 + 指针**，不复述 thesis 全文
- Review 时，任何 thesis 相关更新 MUST 先改 00-thesis.md，再同步引用
- 未来可加 grep-check："thesis 关键词出现在 00-thesis.md 之外的 md 中
  必须以引用形式出现"

### 风险 2：Chain-Position 沦为填空
新 change 作者随便填一个位置，不思考。

**缓解**：
- Review 时检查"位置声明与 proposal 内容是否一致"
- 初期允许多次被打回重写，建立文化
- 后续一旦累计几个正确的范例，新作者可以 cargo-cult（这是可接受的）

### 风险 3：收敛后被"看起来更野心勃勃"的叙事诱惑回滚
未来某次评审意见说"你们做得窄了"，临时又回到四重边界。

**缓解**：
- 在 00-thesis.md 中显式写下"为什么收敛"+"收敛后的贡献特异性"
- Brief v1 四重边界保留为附录，不删 —— 需要时可以指着它说"我们走过
  这条路，选择收敛是深思熟虑的"

## 与其它未归档 change 的关系

| change | 收敛后位置 | 收敛对其的影响 |
|---|---|---|
| `phase-2-roadmap`（未归档路线图） | 每条任务需加 Chain-Position | tasks.md 加前置说明 |
| 未来 `social-graph` | `social-downstream` | proposal `## Why` 必须声明 |
| 未来 `metrics` | `observability`（跨层） | proposal 解释为什么不在四层之一 |
| 未来 `policy-hack` | `algorithmic-input`（反向扰动） | proposal 声明 + 与 attention-channel 的边界 |
| 未来 `conversation` | `social-downstream` | proposal 声明 |
| 未来 `model-budget` | `infrastructure` | proposal 解释为什么不引入新边界 |
