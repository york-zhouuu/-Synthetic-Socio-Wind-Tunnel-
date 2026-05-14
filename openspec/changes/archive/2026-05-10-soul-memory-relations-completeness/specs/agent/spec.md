## ADDED Requirements

### Requirement: do_something handler local_topics arg

`handle_do_something` SHALL accept optional `op.args["local_topics"]: tuple[str,...]`. The
function `synthetic_socio_wind_tunnel/agent/operations/handlers/do_something.py::handle_do_something`当该键
存在且非空时，handler 构造的 LLM prompt SHALL 包含一段 "Recent local topics
in your area:" 列出 topics，让 LLM 在生成 action 时参考。

`local_topics` 缺省 / 为空时 prompt **不**插入此段，保持现有 prompt shape
不变（兼容 1218 测试基线）。

数据源：`data/lanecove/conversation_topics.json`，由 `data_loader::load_conversation_topics()`
载入；caller（如 `_setup_aitown_stack`）在 schedule do_something op 时把 topics
塞进 `op.args["local_topics"]`。

#### Scenario: 缺省时 prompt 不变
- **WHEN** `op.args` 不含 `local_topics` 或为空 tuple
- **THEN** handler 调 LLM 时 prompt 不含 "Recent local topics" 字符串

#### Scenario: 提供时 prompt 含话题段
- **WHEN** `op.args["local_topics"] = ("school zone debate", "parking issue")`
- **THEN** prompt SHALL 含 "Recent local topics" 字符串；至少一个话题文本出现在 prompt 里
