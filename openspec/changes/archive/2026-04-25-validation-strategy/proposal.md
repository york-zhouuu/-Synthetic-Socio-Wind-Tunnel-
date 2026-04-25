## Why

`metrics` 归档日 smoke + `suite-wiring` 跑通后的诚实拷问暴露了项目的
**根基缺陷**：基建已完整，但**装置里被风测试的"东西"（agent 系统）拟真度
不足**。具体：

1. **stub-only suite 是套娃**：variants 强制 hp 走向 target → contest
   检测到 hp 离 target 近 → 我们写进去的答案被自己读出来。
2. **真 LLM 不解决问题**：profile 字段是占位
   （`phase1-baseline.profile-preset-ground-truthed` audit **FAIL**），LLM
   基于 underspecified prompt 输出的是**英文互联网刻板模板**——不是
   Lane Cove 真人。
3. **LLM stereotype 风险未审**：早前 Q2 讨论提出的 swap test / blind test /
   cross-model convergence 都没设流程；agent 行为有多少是
   `ethnicity_group + income_tier` 字段触发的 LLM 偏见无人知晓。
4. **伦理立场未落到代码**：thesis-focus 选了 Hybrid（C 骨 + B 皮 + 拒
   绝 A），但**只在 docs 层声明**——没有把 mirror 实验义务、Ethics
   Statement、forbidden-word guard 写成可 audit 的 publishable
   pre-flight checklist。
5. **没有"什么算成功"的明文**：experimental-design spec 规定了 β 严谨度
   + Diagnosis-Cure-Outcome-Interpretation 报告结构，但**没有定义验证
   类型 taxonomy**——face validity / construct validity / convergent
   validity 等概念散落各处，未形成可引用的 SHALL 规则。

后果：现在跑任何 publishable suite 都是 theatre（stub 套娃 / LLM
刻板）。继续往前推（`agent-calibration` / 真 LLM cost 控制 / 多场地
扩展）之前，需要**先冻结"什么样的证据算 thesis 得到 weak support"**。
否则后续工程没有审稿尺。

本 change 是**纯方法学治理**——不实现任何校准 / 审计代码，只**冻结
validity taxonomy + audit 协议 + pre-publication checklist**。下游
change（`agent-calibration` / `stereotype-audit` / `population-realdata`
等）按本 change 的 spec 执行。

**Chain-Position**: `observability`（治理；不在四层机制链上；但**约束**
所有产出 evidence 的 publishable run）

**Fitness-report 锚点**：
- `phase1-baseline.profile-preset-ground-truthed` 状态 **FAIL**，
  mitigation 指向 `realign-to-social-thesis`——本 change 把这条 audit
  失败重新归位到 `agent-calibration` 下游 change（validation-strategy
  规定校准应该达到什么程度，calibration change 执行）

## What Changes

### 1. 新增 `validation-strategy` capability（NEW）

**纯 spec 性 capability**——不实现代码。冻结：

- **Validity taxonomy**：6 种 validity 类别（construct / internal /
  convergent / face / theoretical fidelity / external——其中 external
  显式拒绝）+ 每类的可操作判据
- **Audit 协议**：3 套 audit（stereotype audit / face validity audit /
  reproducibility lock）的输入 / 流程 / acceptance 阈值
- **Calibration target**：population-level（ABS Census）+ behavioral
  baseline（Google Popular Times / ABS Travel Survey）的对照清单 +
  分布匹配阈值
- **Pre-publication checklist**：任何声称 "evidence" 的 artifact 在
  发布前 SHALL 通过的 8 项检查

### 2. 新增 canonical 文档 `docs/agent_system/18-validation-strategy.md`

与 `00-thesis.md` / `13-research-design.md` 对等地位的 single-source-of-
truth：
- 6 种 validity 的定义 + 在本项目的取舍（要哪几种、明示拒绝哪几种）
- LLM stereotype audit 的 swap-test / blind-test / cross-model 协议
- Face validity 的 Prolific 问卷设计 + acceptance 阈值
- Population & behavioral calibration 的 data source 清单 +
  分布对照统计学
- Reproducibility lock：seed / model_version / prompt_template_hash /
  variant_metadata 的固定方式
- Pre-publication checklist 完整版

### 3. 现有 spec 文档的引用更新（无契约变动）

- `00-thesis.md`：在 "Research Posture" 章节 link `18-validation-strategy.md`
- `13-research-design.md` Part I "Research Posture"：补"validity 类别
  详见 18"
- `16-metrics.md` 的 "已知限制"：明示 metrics 的"内部一致性"已覆盖；
  其它 5 类 validity 由 validation-strategy 规定下游执行
- README "Research Posture" 段：加 validation-strategy 引用
- `phase-2-roadmap` proposal：加 "publishable run 的前置门禁——必须
  通过 validation-strategy 的 pre-publication checklist"

### 4. 引入 `pre-publication checklist` 作为门禁

任何 publishable artifact（report.md / contest.json / poster / paper
draft）SHALL 标注：
- 校准状态（calibration_passed: bool）
- Stereotype audit 状态
- Face validity 状态
- Mirror 实验是否齐备
- Forbidden words 检查是否通过
- Reproducibility lock 是否齐
- Ethics Statement 是否包含
- Acceptance 措辞合规（"evidence consistent with" only）

8 项缺一即标 `[unpublishable preview]`，与 metrics 现有的
`degraded_preliminary_not_publishable` 同精神。

## Non-goals

- **不**实现校准代码（`agent-calibration` change 的事）
- **不**实现 stereotype audit 自动化（`stereotype-audit` 后续 change）
- **不**做 Prolific 问卷（人力流程；spec 只规定**协议**与 acceptance
  阈值）
- **不**爬 ABS / Google Popular Times 数据（spec 列出 data source 与
  对照变量，下游 calibration change 执行）
- **不**改任何已归档 capability 的 spec 契约
- **不**引入新代码模块（`synthetic_socio_wind_tunnel/validation/` 不存在；
  本 change 是 spec + docs 收敛）
- **不**回填历史 publishable 标记（已归档实验的 report 不重新审）

## Capabilities

### New Capabilities

- `validation-strategy`: 方法学治理。冻结 validity taxonomy + audit
  协议 + calibration target + pre-publication checklist。**纯 spec
  capability**——不产 Python 代码；规定下游 change 必须做什么、做到
  什么程度。

### Modified Capabilities

（无 spec 契约变动；只新增引用文档）

## Impact

- **新文件**：
  - `openspec/specs/validation-strategy/spec.md`（归档同步后）
  - `docs/agent_system/18-validation-strategy.md`（canonical 单一事实
    来源）
- **修改文件**（仅引用更新，无 spec 内容改）：
  - `docs/agent_system/00-thesis.md`
  - `docs/agent_system/13-research-design.md`
  - `docs/agent_system/16-metrics.md`
  - `README.md`
  - `openspec/changes/phase-2-roadmap/proposal.md`
- **代码**：零改动
- **测试**：零改动
- **下游影响**：
  - `agent-calibration` change（未来）的 spec MUST cite 本 change 的
    population calibration target
  - `stereotype-audit` change（未来）的 spec MUST cite 本 change 的
    swap-test / blind-test 协议
  - 任何未来的 publishable run（30 seed × 14d × 100 agent × 6 variant）
    在产出前 MUST 通过本 change 的 pre-publication checklist
- **Fitness-audit 影响**：
  - 不直接翻绿任何 audit；但下游 change 完成后会通过本 change 的
    checklist 间接 unblock `profile-preset-ground-truthed` 等条目
