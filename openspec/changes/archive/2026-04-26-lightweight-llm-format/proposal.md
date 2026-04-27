## Why

第一次跑真 LLM (Gemini 3 Flash Preview) 发现：

1. **JSON + Literal enum + 7-字段全严格** 的 prompt 格式对小模型负担过重——
   Gemini 输出 `"action": "visit"` / `"work"` / `"go_home"` 等非法词，被
   `Planner._parse_plan` silent skip → fallback 到原 plan → 没有 replan
   生效信号。
2. 用 `response_schema` enum 强制后能跑，但**抹平了模型间的语言差异**——
   这违背 `validation-strategy` 的 "cross-model convergence" 审计目的（我们
   想看模型差异，不是让 schema 把所有模型挤进同一窄词表）。
3. PlanStep 的 4 类 action（move / stay / interact / explore）是为
   `AgentRuntime.step` dispatch 服务的工程词表，不是表达 agent 真实意图
   的语义词表。强迫 LLM 翻译到这 4 个词损失大量信息（"work at office" →
   "stay" 丢失了"工作"语义；"commute home" → "move" 丢失了"通勤"语义）。
4. 工业实践共识：**prompt 越轻 LLM 越听话**——给结构化的"骨头"（XML 标签
   树），不要给"金刚锁链"（严格 JSON + Literal enum + nullable 嵌套）。
   Anthropic 官方 prompt guide 推荐 XML；Gemini 在 XML 上也表现良好。

本 change 把 Planner 的 LLM I/O 格式从**严格 JSON** 改为**轻量 XML**，
同时引入**同义词映射层**——让 LLM 自由表达 action / social 措辞，我们
post-hoc 翻译到 canonical PlanAction / SocialIntent。结果：
- LLM 输出更自然 / 失败率更低
- 模型间的语言差异在解析前**保留**（写入 `PlanStep.activity` 或 log），
  供未来 cross-model audit
- PlanStep 公共 schema 不变（dispatch / Intent 不动）

**Chain-Position**: `infrastructure`（agent 内部 LLM I/O；不引入新边界、
不动思路链条）

**Fitness-report 锚点**：本 change 不直接对应已有 audit 失败；动机来自
2026-04-26 的真 LLM 跑通 + 用户反馈"格式要求过重"。

## What Changes

### 1. `agent/planner.py` 的两处 prompt 改为 XML 输出

**Daily plan**（`_PLAN_PROMPT_TEMPLATE`）和 **replan**（`_build_replan_prompt`）
都改为要求 LLM 输出 XML：

```xml
<plan>
  <step>
    <time>8:00</time>
    <destination>cafe_main</destination>
    <action>visit cafe_main to find the historical note</action>
    <duration>30</duration>
    <social>open_to_chat</social>
  </step>
  ...
</plan>
```

字段语义：
- `<time>`（必填）：开始时刻（如 `8:00`）
- `<destination>`（可选）：去哪里；缺失即 `None`
- `<action>`（**自由文本**）：LLM 任意描述意图（"visit" / "work" / "commute"）
- `<duration>`（可选）：分钟；缺失默认 30
- `<social>`（**自由文本**）：LLM 任意社交意图

### 2. 新解析器 `_parse_xml_plan`

替代 `_parse_plan`：
- 用 stdlib `xml.etree.ElementTree` 解析（无新依赖）
- 容错：忽略未知子元素 / 多余空格 / 大小写
- **同义词映射层**（`_normalize_action` + `_normalize_social_intent`）：
  - "visit" / "go" / "go_home" / "commute" / "walk" / "travel" → `move`
  - "work" / "rest" / "sleep" / "eat" / "wait" → `stay`
  - "talk" / "chat" / "meet" → `interact`
  - "wander" / "search" / "investigate" / "find" → `explore`
  - 未知映射 → 默认 `stay` + log debug 记录（供未来扩展词表）
- 保留 LLM 原始措辞到 `PlanStep.activity`（如果 activity 字段空）；
  优先保留显式 `<activity>`

### 3. 同步更新 `StubReplanLLM`

`tools/suite_stub_llm.py::_plan_toward` 从输出 JSON 改为输出 XML 形态；
保持其它 dispatch 逻辑不变。

### 4. 移除 Gemini 的 `response_schema`

`_GeminiClient.generate` 不再设 `response_schema`；让 Gemini 自由用 XML
（schema 只为 JSON 强制 enum 设计；XML 路径下不需要）。
保留 `thinking_budget=0`（关 thinking）。

### 5. 测试

- `tests/test_planner_xml_parsing.py`：
  - 解析合规 XML
  - 容忍多余空白 / 注释
  - 同义词映射（"visit" → "move" 等）
  - 未知 action → fallback "stay" + log warning
  - 缺失 `<destination>` → None
  - 缺失 `<duration>` → 30
- 现有 `tests/test_planner_replan.py`：StubLLM mock 改为输出 XML
- 现有 `tests/test_suite_stub_llm.py`：StubReplanLLM 输出验证改为 XML 解析

## Non-goals

- **不**改 `PlanStep` / `DailyPlan` / `Planner` public API 契约
  （`agent` capability spec 的 SHALL 字段不动；schema 仍是 4 类 PlanAction
  + 3 类 SocialIntent）
- **不**改 `AgentRuntime.step` 的 dispatch 逻辑
- **不**实现"自动学习同义词"——同义词表是手写 dict，简单可控
- **不**实现 conversation 类的 LLM 输出（不属于本 change）
- **不**对 Anthropic Haiku 调优（XML 对 Anthropic 更友好；不需要特殊处理）
- **不**给 PlanStep 加 `raw_action_label` 字段（用户讨论里的 Option B
  延后；本 change 只动 prompt + parser）

## Capabilities

### Modified Capabilities

- `agent`: `Planner` 的 prompt 模板 + parser 实现内部改动；公共 API 不变。
  spec MODIFIED 体现在 "每日计划生成" / "Planner.replan 方法" 两条
  Requirement 的描述中——把"输出 JSON 数组"改为"输出 XML"，并补容错语义。

### New Capabilities

（无）

## Impact

- **修改文件**：
  - `synthetic_socio_wind_tunnel/agent/planner.py`（prompt 模板 + 新 parser
    + 同义词映射）
  - `tools/suite_stub_llm.py`（StubReplanLLM 输出 XML；_GeminiClient 移除
    response_schema）
- **新增测试**：
  - `tests/test_planner_xml_parsing.py`（同义词 + 容错）
- **修改测试**：
  - `tests/test_planner_replan.py`（mock LLM 输出格式）
  - `tests/test_suite_stub_llm.py`（XML 解析验证）
- **不改**：
  - `synthetic_socio_wind_tunnel/agent/profile.py` / `personality.py` /
    `runtime.py`
  - `tools/run_variant_suite.py` / `run_multi_day_experiment.py`（CLI 不变）
  - 任何 spec 契约的 SHALL 字段（PlanStep schema 不变）
- **前置依赖**：无（独立修复）
- **下游影响**：
  - 真 LLM 跑成功率上升；cross-model audit 现在能看到模型间真实差异
- **Fitness-audit 影响**：无（不改 audit 探针）
- **性能**：parser XML 比 JSON 略慢（μs 级；可忽略）；prompt 长度略增
  （XML 标签开销 ~10-15% tokens）
