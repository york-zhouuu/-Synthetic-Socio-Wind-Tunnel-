## ADDED Requirements

### Requirement: AgentRuntime.familiar_with 便捷方法

`AgentRuntime` SHALL 提供方法：

```
familiar_with(other_agent_id: str, threshold: float = 0.1) -> bool
```

- 方法 SHALL 是 `social_graph` 的薄封装：`return self._social_graph.get_tie(self.profile.agent_id, other_agent_id).strength > threshold`（若 tie 存在），否则 False
- AgentRuntime SHALL 通过 optional `social_graph: SocialGraphService | None = None` 字段持有引用；未注入时 `familiar_with` SHALL 返回 False（不抛异常）
- 方法 MUST NOT 调 LLM；O(1) 复杂度；可在每 tick 多次安全调用

#### Scenario: 已注入 social_graph 且有 tie

- **WHEN** runtime 注入 social_graph；emma 跟 linda 累积 encounter_count=5
  （strength ≈ 0.33 > 0.1）
- **THEN** `emma_runtime.familiar_with("linda")` SHALL 返回 True

#### Scenario: 已注入但无 tie

- **WHEN** runtime 注入 social_graph，但 emma 跟 john 从未 encounter
- **THEN** `emma_runtime.familiar_with("john")` SHALL 返回 False（不抛异常）

#### Scenario: 未注入 social_graph 时降级返回 False

- **WHEN** runtime 构造时未传 social_graph（默认 None）
- **THEN** `runtime.familiar_with(任何 id)` SHALL 返回 False（不查询 memory，不抛异常）

#### Scenario: 自定义 threshold 影响判定

- **WHEN** emma 跟 linda 累积 encounter_count=2（strength ≈ 0.167）
- **THEN** `emma_runtime.familiar_with("linda", threshold=0.1)` SHALL 返回 True
- **AND** `emma_runtime.familiar_with("linda", threshold=0.2)` SHALL 返回 False
