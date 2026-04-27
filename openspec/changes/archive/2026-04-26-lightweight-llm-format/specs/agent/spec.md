## ADDED Requirements

### Requirement: Planner LLM I/O 使用轻量格式 + 容忍自由词汇

`Planner` SHALL 使用 XML（或同等轻量结构化格式）作为 LLM I/O 形态——
不强制 LLM 输出严格 JSON 与 Literal enum；解析层 SHALL 容忍自由 action /
social_intent 措辞，通过同义词映射归一化到 canonical PlanAction /
SocialIntent。

设计意图（见 `lightweight-llm-format` change design D1-D5）：
- LLM（特别是小模型如 Gemini Flash）在严格 JSON + 多 Literal 下输出
  失败率高
- Cross-model audit（`validation-strategy` Part II）需要保留模型间语言
  差异；schema enum 强制会抹平
- PlanStep 的 PlanAction / SocialIntent 仍是 dispatch 工程契约；canonical
  词表不变；只是**允许 LLM 用自由词汇 + post-hoc 映射**

具体要求：

1. Prompt 输出格式 SHALL 使用 XML 标签结构（如 `<plan><step><time>.../>...
   </step></plan>`）；MUST NOT 要求严格 JSON + Literal enum
2. Parser SHALL 用 stdlib `xml.etree.ElementTree`，无新依赖
3. 解析失败 / 字段缺失 / 未知子元素 SHALL 容忍（与现有 `_parse_plan` 失败
   = 空 list 语义一致）；MUST NOT 抛异常
4. action 字段 SHALL 容忍自由文本（如 `visit` / `work` / `go_home`）；
   通过手写同义词字典映射到 canonical PlanAction（`move` / `stay` /
   `interact` / `explore`）；未知词 → fallback `stay` + `logger.debug`
   记录原始词
5. social_intent 字段 SHALL 容忍自由文本；同上映射到 canonical SocialIntent
   （`alone` / `open_to_chat` / `seeking_company`）
6. LLM 原始 action 措辞 SHALL 保留到 `PlanStep.activity`（若 LLM 未显式
   提供 `<activity>` 时）；保留信息供未来 cross-model audit
7. PlanStep / DailyPlan / Planner 公共 API 契约 MUST NOT 改变

#### Scenario: XML 输出被正确解析
- **WHEN** LLM 返回 `<plan><step><time>8:00</time><destination>cafe</destination><action>move</action><duration>30</duration><social>alone</social></step></plan>`
- **THEN** `Planner._parse_xml_plan` SHALL 返回 1 条 PlanStep，
  `time="8:00"` / `destination="cafe"` / `action="move"` / `social_intent="alone"`

#### Scenario: 自由 action 词汇通过同义词映射
- **WHEN** LLM 返回 `<step>...<action>visit cafe to find note</action>...</step>`
- **THEN** PlanStep.action SHALL == `"move"`（visit → move 同义映射）；
  `PlanStep.activity` SHALL 含 `"visit cafe to find note"` 或 LLM 提供的
  `<activity>` 文本

#### Scenario: 未知 action 词 fallback
- **WHEN** LLM 返回 `<step>...<action>flying</action>...</step>`
  （flying 不在同义词表里）
- **THEN** PlanStep.action SHALL == `"stay"`（fallback）；
  Logger SHALL 输出 debug 级 "unknown action token: flying"

#### Scenario: 缺失字段优雅 degrade
- **WHEN** LLM 返回 `<step><time>9:00</time><action>move</action></step>`
  （缺 destination / duration / social / activity）
- **THEN** PlanStep SHALL 构造成功；destination=None；duration_minutes=30
  （默认）；social_intent="alone"（默认）；activity="" 或 action 文本

#### Scenario: 完全无效输出 fallback
- **WHEN** LLM 返回纯文本 `"sorry, I cannot help"`（无 XML）
- **THEN** parser SHALL 返回空 list；`Planner.generate_daily_plan` 返回
  空 steps DailyPlan；`Planner.replan` 返回 current_plan 的副本（与现有
  失败语义一致）

#### Scenario: 公共契约保持不变
- **WHEN** Planner.generate_daily_plan / Planner.replan 被调用，无论 LLM
  输出何种格式（成功 / 失败 / 自由词）
- **THEN** 返回值 SHALL 仍是合法 DailyPlan；包含 0+ 个 PlanStep；每个
  PlanStep 的 `action` 字段 SHALL 为 PlanAction Literal 之一（4 类）；
  `social_intent` SHALL 为 SocialIntent Literal 之一（3 类）


### Requirement: 同义词映射不在 spec 层面写死

同义词映射表（如 `visit → move` / `work → stay`）SHALL 作为 implementation
detail 存在 `synthetic_socio_wind_tunnel/agent/planner.py` 内部；spec 不
枚举具体映射，只规定行为：必须支持映射、未知 → fallback、原始措辞保留。

未来增删映射条目 MUST NOT 触发 spec 改动；属代码迭代级别。

#### Scenario: 同义词表迭代不破契约
- **WHEN** 团队向同义词表新增 `"jog" → "move"`
- **THEN** spec MUST NOT 要求修改；只需更新 `_ACTION_SYNONYMS` dict +
  对应单元测试覆盖
