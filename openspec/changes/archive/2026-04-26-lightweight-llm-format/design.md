## Context

2026-04-26 的真 LLM smoke 暴露：现有 Planner 的 LLM I/O 格式（严格 JSON
+ 7 字段 + 2 个 Literal enum）对 Gemini 3 Flash Preview 太重。Gemini
默认输出 `action="visit"/"work"` 等非法词；schema enum 强制能跑但抹平
模型差异。

工业实践共识：prompt 越轻 LLM 越听话。Anthropic 官方推荐 XML；Gemini
在 XML 上表现也好；其它 SDK（OpenAI / Mistral）解析 XML 同样无问题。

PlanStep 的 4 类 PlanAction Literal 是**dispatch 工程词表**——对齐
`AgentRuntime.step` 的 Intent 类型（MoveIntent / WaitIntent / ...）。
LLM 用 "visit" / "work" 等自然语言更好；只需在 parser 里 normalize 到
canonical 即可。

## Goals / Non-Goals

**Goals**：
- LLM I/O 格式从严格 JSON → 轻量 XML
- Parser 接受**自由 action 词汇**，post-hoc 映射到 canonical PlanAction
- 真 LLM 跑成功率上升（不再因 schema 不匹配 silent fail）
- Cross-model audit 能保留模型间语言差异（log 原始措辞）
- StubReplanLLM 同步改为 XML（保持工具链一致）

**Non-Goals**：
- 不改 PlanStep / DailyPlan / Planner public API
- 不动 AgentRuntime.step / Intent dispatch
- 不引入 jinja / xmltodict / lxml 等新依赖（stdlib `xml.etree` 够用）
- 不实现自动学习同义词（手写 dict 即可；30 词足以覆盖常见 LLM 表达）
- 不补 PlanStep.raw_action_label 字段（避免动 spec；先验证 XML 路径）

## Decisions

### D1：选 XML 而非 YAML / Markdown / TOML

**选择**：XML

**备选**：
- **JSON + 自由 action**：仍要求 LLM 凑齐 JSON 引号 / 逗号 / 嵌套；
  小模型还是脆弱
- **YAML**：缩进敏感；LLM 容易写错；解析需 `pyyaml`（新依赖）
- **Markdown bullet**：`1. 8:00 → cafe (visit, 30min, alone)`——最轻；
  但要求规整（破折号 / 括号位置）；解析需手写正则；调试时 LLM 错位很
  难看出
- **XML** ✓：标签结构对 LLM 友好（Anthropic 训练数据里就有大量 XML）；
  错位时仍可解析部分；stdlib 解析；缺字段优雅 degrade

### D2：XML 标签命名

**选择**：
```xml
<plan>
  <step>
    <time>8:00</time>
    <destination>cafe_main</destination>
    <action>visit cafe to find note</action>
    <duration>30</duration>
    <social>open_to_chat</social>
  </step>
</plan>
```

**为什么不用 attribute（`<step time="8:00">...`)**：attribute 内嵌长文本
（如 `<step action="visit cafe to find note">`）易让 LLM 写错引号；
child element 形式更稳健。

**为什么字段名缩短**（`duration` 而非 `duration_minutes`，`social` 而非
`social_intent`）：减少 token 消耗 + LLM 注意力分散；解析时映射到
canonical 字段名。

### D3：解析容错策略

**选择**：
- 用 `xml.etree.ElementTree.fromstring`，try/except 捕获 ParseError
- 找不到 `<plan>` 根 → 尝试 wrap 加根：`<plan>{raw}</plan>` 再解析
- 仍失败 → 返回空 list（与现有 `_parse_plan` 失败语义一致）
- 单个 `<step>` 缺字段 / 字段值非法 → 跳过该 step，记 logger.debug；
  其它 step 继续
- 未知子元素（如 LLM 多写 `<priority>`）→ 静默忽略

**Rationale**：保持当前"失败 = 空 list → fallback 原 plan"的语义；不抛异常。

### D4：同义词映射表

**选择**：手写 dict，覆盖常见 LLM 输出。

```python
_ACTION_SYNONYMS = {
    "move": "move", "go": "move", "go_home": "move", "goto": "move",
    "visit": "move", "travel": "move", "walk": "move", "drive": "move",
    "commute": "move", "head": "move", "head_to": "move",

    "stay": "stay", "wait": "stay", "rest": "stay", "sleep": "stay",
    "work": "stay", "eat": "stay", "drink": "stay", "read": "stay",
    "study": "stay", "watch": "stay",

    "interact": "interact", "talk": "interact", "chat": "interact",
    "meet": "interact", "greet": "interact", "converse": "interact",

    "explore": "explore", "wander": "explore", "search": "explore",
    "investigate": "explore", "find": "explore", "look": "explore",
    "discover": "explore",
}

_SOCIAL_SYNONYMS = {
    "alone": "alone", "private": "alone", "solo": "alone",
    "open_to_chat": "open_to_chat", "open": "open_to_chat",
    "casual": "open_to_chat", "friendly": "open_to_chat",
    "seeking_company": "seeking_company", "social": "seeking_company",
    "looking_for_company": "seeking_company",
}
```

未知词 → fallback `"stay"` / `"alone"` + `logger.debug` 记 unknown
词以便未来扩展。

### D5：LLM 原始措辞保留位置

**选择**：保留到 `PlanStep.activity`：
- 如 LLM 显式提供 `<activity>` → 用它（兼容老 prompt 仍含 activity）
- 否则 `<action>` 文本作 activity（"visit cafe to find note"）
- 同义词映射结果作 `action`（canonical "move"）

**Rationale**：activity 字段已存在，自由文本；当前默认空字符串无意义。
让它承载 LLM 的"语义层"意图，符合 PlanStep 双层语义（dispatch +
narrative）。

### D6：StubReplanLLM 输出 XML

**选择**：StubReplanLLM 也输出 XML 格式，保持解析路径单一。

**Why**：
- 测试简单（只一个 parser 路径）
- 真 LLM / stub 行为接近（除了内容生成）
- StubReplanLLM 的 dispatch 逻辑（按 variant_name）不变；只输出格式变

### D7：Gemini 客户端去掉 response_schema

**选择**：`_GeminiClient.generate` 不再设 `response_schema`；让 Gemini
自由用 XML。

**保留**：`thinking_budget=0`（关 thinking）；mime type 默认 text/plain。

**Rationale**：response_schema 是为强制 JSON enum 设计的；XML 路径下
冗余且抹平模型差异。

### D8：daily_plan 与 replan 共享同一 prompt 格式 + parser

**选择**：是。

**Why**：
- 减少代码重复；parser 一份
- 测试覆盖更全
- 未来 LLM 升级 / vocab 调优受益于两边

**Risk**：daily_plan 比 replan 步数多（一日 10-20 步 vs replan 3-5 步）。
XML 体积更大；Gemini 1M token 上下文不是问题。

### D9：Spec MODIFIED 写法

**选择**：MODIFY agent capability 的 "每日计划生成" 和 "Planner.replan
方法" 两条 Requirement，把 "输出 JSON 数组" 段改为 "输出 XML 形式"，
新增 "解析 SHALL 容忍未知 action 词汇并通过同义词映射" 的 scenario。

**不动**：PlanStep 的 PlanAction / SocialIntent Literal 仍为 4 类 / 3 类
（dispatch 契约）。

## Risks / Trade-offs

**[Risk 1] 现有依赖 JSON 输出的代码 / 测试遗漏更新**
→ 缓解：grep `_parse_plan` / `JSON 数组` / `model_dump_json` 全仓；逐处审

**[Risk 2] XML 解析在 prompt 注入下出问题**
→ Prompt 是我们 build 的，不是用户输入；agent.profile 字段如果含 XML
  特殊字符（`<` / `&`）需 escape——Profile 字段在测试里基本是中英文
  可控；加一个 `_escape_xml(s)` 函数处理 prompt 字段插入即可

**[Risk 3] LLM 不老实，仍输出 JSON 或 plain text**
→ 解析容错：root 找不到 `<plan>` 时尝试 wrap；都失败返回空 list →
  fallback 到原 plan（与现状一致）。不抛异常

**[Risk 4] 同义词表覆盖不全**
→ 缓解：未知词 fallback "stay"；logger.debug 记 unknown；未来扩展

**[Risk 5] StubReplanLLM 在所有 variant 下输出格式同步**
→ 改 `_plan_toward` 输出 XML；同 dispatch 逻辑不变

**[Risk 6] Token 成本上升 ~10-15%（XML tag 开销）**
→ 可接受；prompt 字段名简化（duration vs duration_minutes）部分抵消；
  且 LLM 通过率上升带来的实验有效率提升远大于 token 成本

**[Risk 7] daily_plan 步数多 → XML 大 → 解析慢**
→ μs 级开销；不构成性能瓶颈

## Migration Plan

1. 实现 `_parse_xml_plan` + `_normalize_action` + `_normalize_social_intent`
   helpers
2. 修改 `_PLAN_PROMPT_TEMPLATE` + `_build_replan_prompt`：输出 XML 格式
3. 修改 `Planner.generate_daily_plan` / `Planner.replan`：调新 parser
4. 同步 StubReplanLLM 的 `_plan_toward` 输出 XML
5. 移除 `_GeminiClient` 的 response_schema
6. 更新现有测试 + 加新测试
7. 跑 full pytest + 6-variant smoke + 真 Gemini smoke
8. archive sync agent spec

**回滚**：本 change 是 capability 内部改动；如需回滚 git revert + 重跑
测试。下游 CLI / suite-wiring 都不受影响。

## Open Questions

1. **Q1**: 是否同时改 `MemoryService.run_daily_summary` 的 LLM prompt
   到 XML？
   倾向：本 change 不改——daily_summary 输出是自由文本（不需结构化），
   现有 prompt 已 LLM-friendly；范围控制
2. **Q2**: 同义词表是否进 spec？还是 implementation detail？
   倾向：spec 只规定"SHALL 容忍未知 action 并 fallback"——不写死表；
   表存代码里方便迭代
3. **Q3**: Anthropic Haiku 是否也需要测试？
   倾向：本 change 不强制；如果未来跑真 Anthropic 时挂了再补
4. **Q4**: 是否给 logger.debug 加 hooks 让外部能 collect 同义词使用统计？
   倾向：不做；logger.debug 已够；未来 cross-model audit 时如需要再加
