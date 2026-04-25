## ADDED Requirements

### Requirement: Validity taxonomy 冻结（4 接受 / 1 拒绝 / 1 stub）

`validation-strategy` capability SHALL 冻结项目接受的 validity 类别，
明示拒绝的类别，以及保留为未来扩展的类别：

**接受**（每条 SHALL 在 publishable artifact 中可被验证）：
1. **Construct validity**：每 variant operationalization 忠实于其
   theoretical lineage（policy-hack spec 已有 success_criterion /
   failure_criterion 字段）
2. **Internal consistency**：seed 跨 run 可复现（`seed_pool` + 固定
   model_version + prompt_template_hash 完全决定 trajectory_deviation_m
   分布）
3. **Convergent validity**：相同 thesis-层信号在多个 metric 维度同向
4. **Face validity**：≥3.5/5 平均分（详见 Requirement: Face validity
   protocol）
5. **Theoretical fidelity**：Granovetter 弱关系 / Putnam 社会资本 /
   Shannon 注意力稀缺等概念在代码中有可计算映射；每 variant 元数据的
   `theoretical_lineage` 字段引用具体作者 + 著作

**拒绝**（publishable artifact MUST NOT 声称这些）：
6. **External validity (predictive)**：不声称合成 agent 对真实 Lane Cove
   居民的行为有 predictive accuracy；不做 RCT 校准

**Stub**（未来扩展，本项目 scope 外）：
- **Ecological validity**：单场地 Lane Cove；不声称跨社区泛化

#### Scenario: Publishable artifact 显式拒绝外部 validity 声明
- **WHEN** 任一 publishable report.md / poster / paper draft 包含数字
  effect size
- **THEN** artifact SHALL 包含明示语句类似 "this is in-simulation
  effect size only; no claim of predictive validity vs real residents"
- **AND** 全文 grep "predictive validity" 结果应仅出现在 disclaimer 中

#### Scenario: Theoretical fidelity 引用必填
- **WHEN** `policy-hack` 的 variant.metadata_dict() 被序列化进
  RunMetrics.metadata.variant_metadata
- **THEN** `theoretical_lineage` 字段 SHALL 非空且引用具体学派作者
  （e.g., "Shannon 信息论 + Wu《Attention Merchants》"）


### Requirement: Stereotype audit 三协议

任何 publishable run 在生成 contest 前 SHALL 通过以下三协议：

**Swap test**：
- 同 profile 改 `ethnicity_group` 至少一个对照对（e.g., Han Chinese →
  Anglo-Australian）
- 跑同 seed × 同 variant × 同 day_index × 同 model_version
- 测量 trajectory_deviation_m 与 plan diversity 的差异
- **Stub 路径 acceptance**：差异 ≤ 5%（绝对值）
- **Real LLM 路径 acceptance**：差异 ≤ 10%
- 超阈值 → audit FAIL → publishable 不接

**Blind test**：
- 移除 `ethnicity_group` 字段；其它 profile 字段保持
- 跑同 scenario
- 测量 trajectory / encounter 与含-ethnicity 版本的相关
- **Acceptance**：≥80% seed 重合（trajectory_deviation_m 差异在 IQR
  之内）→ ethnicity 字段对 LLM prompt 影响有限——可保留
- 否则 → ethnicity 字段主导 → audit FAIL

**Cross-model convergence**：
- 同 scenario / 同 seed / 同 variant 跑两个 model（Haiku + Sonnet）
- 测量 evidence_alignment 是否一致（contest 行同 verdict）
- 不一致 → 模型层不稳定 → publishable 不接

#### Scenario: Stub-only run 跳过 cross-model 但其它两条仍跑
- **WHEN** publishable run 用 StubReplanLLM
- **THEN** swap test + blind test SHALL 跑；cross-model 标记 N/A
  并在 artifact disclose

#### Scenario: 任一协议 FAIL 阻塞发布
- **WHEN** swap test 差异 7%（stub 路径，超 5% 阈值）
- **THEN** pre-publication checklist 第 2 项 SHALL ✗；
  artifact 标 `[unpublishable preview]`


### Requirement: Face validity protocol

任何 publishable suite SHALL 配套一次 face validity audit，按以下协议
执行：

- **样本采集**：M=10 条 agent narratives 抽样（每 variant 至少 1 条
  代表）
- **审阅者**：N=20 真人，优先 Lane Cove / Sydney resident 资格
  （Prolific 或同等平台）
- **评分**：5-Likert 三题
  - "这段日记读起来像真实居民写的吗？" 1-5
  - "这位 agent 的行为符合 Lane Cove 居民的日常吗？" 1-5
  - 开放回答："最不像的一段是什么？为什么？"
- **Acceptance**：M=10 条平均得分 ≥ 3.5/5 **AND** ≤20% 评分 ≤2

不达 → publishable 不接；calibration / prompt template / variant 模板
重做后重审。

频率：
- 每个 publishable suite 必跑一次
- LLM 版本变化 / `LANE_COVE_PROFILE` 变化 / prompt template 变化 → 重跑

#### Scenario: face validity 失败时 artifact 标记
- **WHEN** Prolific 结果平均 3.2/5（低于 3.5 阈值）
- **THEN** report.md 顶部 SHALL 标 `[unpublishable preview: face
  validity failed avg=3.2]`

#### Scenario: 抽样多样化
- **WHEN** suite 含 6 variants
- **THEN** M=10 narrative 抽样 SHALL 覆盖至少 5 个 variant 的代表
  agent；不能全选 baseline


### Requirement: Population calibration target

`validation-strategy` SHALL 规定下游 calibration change（如
`agent-calibration`）校准 `LANE_COVE_PROFILE` 时对照 ABS Census 2021
Lane Cove SA2，覆盖至少以下 6 维度：

1. Age distribution（5 岁分组）
2. Gender ratio
3. `housing_tenure`（own / mortgage / rent / public housing）
4. `income_tier`（low / mid / high；按当地中位数定义）
5. `ethnicity_group`（按 ancestry 字段聚合）
6. `work_mode`（commute / remote / shift / not-working）

**距离指标**：每维 chi-squared（离散）或 Kolmogorov-Smirnov（连续）

**Acceptance**：
- **Strict**：6 维全 p > 0.10（弱拒绝零假设；分布无显著偏离）
- **Best-effort**：≥4 维 p > 0.10 且 publishable artifact disclose 缺
  哪 2 维

#### Scenario: 校准达标后 fitness-audit 翻绿
- **WHEN** `agent-calibration` 完成且 6 维 chi-squared/KS p > 0.10
- **THEN** `phase1-baseline.profile-preset-ground-truthed` audit
  status SHALL 变为 PASS

#### Scenario: best-effort 路径 disclose 必须明示
- **WHEN** 5 维 pass，但 `ethnicity_group` p = 0.05（弱失败）
- **THEN** 任何引用 LANE_COVE_PROFILE 的 publishable artifact SHALL
  含 disclose："5/6 dimensions passed; ethnicity_group not aligned
  (p=0.05)"


### Requirement: Behavioral baseline calibration target

`build_scripted_plan` 或其继任 plan 生成器 SHALL 对照真实出行 / POI
访问数据校准；本 change 规定数据源与 acceptance：

**Source 1**：ABS Travel Survey 2021 (Sydney)
- 对照：journey-to-work origin-destination 矩阵 + departure-time
  distribution
- Sim 中：agent first commute step 起点 → destination + 时间
- 距离指标：OD 矩阵 chi-squared；时间分布 KS

**Source 2**：Google Popular Times (top-20 Lane Cove POIs)
- 对照：每 POI 周一-周日 24h hourly visit distribution
- Sim 中：相同 POI baseline 14-day run hourly visit count
- 距离指标：Earth Mover's Distance per POI

**Acceptance**：
- ≥80% POIs 的 EMD < 0.20
- OD 矩阵 chi-squared p > 0.10

#### Scenario: 80% POI 命中阈值
- **WHEN** 20 个 POI 中 17 个 EMD < 0.20（85%），3 个超阈
- **THEN** behavioral calibration SHALL 视为 passed；artifact disclose
  3 个超阈 POI 的名字

#### Scenario: 不足 80% 不达
- **WHEN** 仅 12/20 POI EMD < 0.20（60%）
- **THEN** calibration FAIL；publishable 阻塞


### Requirement: Reproducibility lock 七字段

Publishable run 的产物 SHALL 在 `MultiDayResult.metadata` 与
`report.md` 顶部包含以下七字段；任一字段变化 → 不能直接对比新旧 run
（视为不同实验配置）：

1. `seed_pool: list[int]`（30 条）
2. `model_version: str`（"claude-haiku-4-5-20251001" 或 "stub:vN"）
3. `prompt_template_hash: str`（sha256；stub 路径下记 "stub:<variant_name>"）
4. `LANE_COVE_PROFILE_hash: str`（sha256 of profile config）
5. `variants_loaded: dict[str, str]`（variant_name → variant code hash）
6. `code_commit: str`（git rev-parse HEAD）
7. `phase_config: dict`（baseline_days / intervention_days / post_days）

#### Scenario: metadata 完整可被外部验证
- **WHEN** publishable run 写出 seed_42.json
- **THEN** `run_metrics.extensions` SHALL 含上述七字段
- **AND** 字段 6（code_commit）SHALL 可在 git log 中找到

#### Scenario: 字段变化触发重跑要求
- **WHEN** prompt_template 改一行后，旧 publishable artifact 与新 run
  做对比
- **THEN** 任何 cross-run claim SHALL 显式标注 prompt_template_hash
  changed；不能直接横向比较 effect size


### Requirement: Pre-publication checklist 8 项

Validation-strategy SHALL 强制 publishable artifact（report.md /
contest.json / poster / paper draft）发布前在 metadata 或文档头部按以下
8 项标注 ✓/✗：

1. Calibration passed (Population D4 + Behavioral D5)
2. Stereotype audit passed (D2 三协议)
3. Face validity passed (D3 Prolific 问卷)
4. Mirror experiment included (≥1 paired mirror 等级交付)
5. Forbidden words check passed (artifact 全文无 "proved / falsified /
   confirmed / refuted")
6. Reproducibility lock complete (D6 七字段全填)
7. Ethics Statement included (research-design Part V 完整段)
8. Acceptance language compliant (仅 "evidence consistent with /
   not consistent with"; 无 "X confirms Y" 等)

任一 ✗ → artifact SHALL 标 `[unpublishable preview]`，禁止发布或宣称
"evidence"。

#### Scenario: 8 项全 pass 才能去掉 preview 标记
- **WHEN** report.md 顶部 6/8 ✓
- **THEN** report.md SHALL 含 `[unpublishable preview: 2/8 checklist
  items failed]` banner

#### Scenario: Acceptance language scan
- **WHEN** report.md 全文含字符串 "the experiment proved H_info"
- **THEN** checklist item 8 SHALL ✗；artifact unpublishable


### Requirement: 下游 change 引用本 spec

下游执行 validation 协议的 change 的 `## Why` 章节 SHALL 引用本 spec
的对应 Requirement。范围至少包括 `agent-calibration` /
`stereotype-audit` / `population-realdata` / `behavioral-calibration` /
`face-validity-protocol` 等命名 change。

引用形式 SHALL 至少包含：
- 本 spec 的 Requirement title（e.g., "Population calibration target"）
- acceptance 阈值数字（如 6 维 p > 0.10）
- "完成本 change 后 fitness-audit 中 X 条目从 FAIL 变 PASS" 的 audit
  trail

#### Scenario: agent-calibration change 引用合规
- **WHEN** 未来某 change 名为 `agent-calibration` 的 proposal 被审
- **THEN** 其 `## Why` SHALL 引用本 spec 的 "Population calibration
  target" requirement + acceptance 阈值（6 维 p > 0.10）+ 对应
  fitness-audit 条目（`phase1-baseline.profile-preset-ground-truthed`）


### Requirement: 本 change 不引入代码

`validation-strategy` capability SHALL 是纯 spec capability：
- `synthetic_socio_wind_tunnel/validation/` 目录 MUST NOT 被本 change
  创建
- 任何 audit / calibration 实现 MUST 在下游 change 中执行
- 本 change 仅产 docs + spec 文件

#### Scenario: 归档后 grep 验证无代码改动
- **WHEN** 归档 validation-strategy change 后跑
  `git diff synthetic_socio_wind_tunnel/`（vs archive 前 commit）
- **THEN** 输出 SHALL 为空（无 .py 改动）
