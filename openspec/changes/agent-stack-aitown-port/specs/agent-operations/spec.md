## ADDED Requirements

### Requirement: PendingOp 数据模型

`synthetic_socio_wind_tunnel/agent/operations/models.py` SHALL 定义 frozen dataclass `PendingOp`：

```
op_id: str                       # uuid 或 op_{agent_id}_{tick}_{kind}
agent_id: str
kind: Literal["do_something", "generate_message", "remember_conversation",
              "reflect", "score_importance"]
created_tick: int
timeout_tick: int                # ai-town 用 ACTION_TIMEOUT=120s；SSWT 算 simulated_time
args: dict[str, Any]             # op-specific 输入
```

- frozen / 不可变
- timeout_tick = created_tick + ceil(120 / tick_minutes)（默认 24 ticks，120 simulated minutes）
- 每 agent 同时最多 1 个 pending op

#### Scenario: 同 agent 多个 op 拒绝

- **WHEN** AgentRuntime 已有 pending_operation；尝试 schedule 第二个
- **THEN** OperationPool SHALL 抛 `ConcurrentOperationError`，要求 caller 先 cancel 老 op

#### Scenario: 跨 tick 超时

- **WHEN** PendingOp 在 25 ticks 后仍未完成
- **THEN** OperationPool SHALL 在下一次 process_tick 标记为 timed_out，AgentRuntime.pending_operation 清空

### Requirement: OperationPool async 调度

`synthetic_socio_wind_tunnel/agent/operations/pool.py` SHALL 定义 `OperationPool` 类：

```
schedule(op: PendingOp, handler_kwargs) -> None         # async 调度
process_pending(tick: int) -> list[OperationResult]    # 收所有完成的，写回 input queue
cancel(agent_id: str, reason: str) -> bool              # 显式取消
get_pending(agent_id: str) -> PendingOp | None
```

- `process_pending` SHALL 通过 `asyncio.gather` 并发执行所有 in-flight handlers
- 每个 handler 的 kwargs 包含 `llm_client`（按 op kind tier 路由：sonnet/haiku/nano）
- 完成的 op 结果 SHALL 在 `tick_inputs[agent_id]` 队列中等待，由下 tick 开头的 AgentRuntime.step() 消费
- 超时的 op SHALL 不写 input queue；改写 `op_timeout_log` 供 metrics 采样

#### Scenario: 多 agent 并发

- **WHEN** 100 protagonist agents 同时 schedule do_something op；调 `process_pending`
- **THEN** 100 op handlers SHALL 并发跑（asyncio.gather），不串行；总耗时 SHALL ≤ max(individual op time) + 10%

#### Scenario: 超时清理

- **WHEN** op 已 schedule 25 ticks 还未返回
- **THEN** process_pending SHALL 标记其为 timed_out；agent 的 pending_operation 清空；agent 下 tick 可恢复正常决策树

### Requirement: 5 个 op handler 实现

`synthetic_socio_wind_tunnel/agent/operations/handlers/` SHALL 实现：

```python
async def handle_do_something(op, *, agent, atlas, ledger, llm_client, ...) -> OperationResult
async def handle_generate_message(op, *, agent, dialogue, memory, llm_client, ...) -> OperationResult
async def handle_remember_conversation(op, *, agent, dialogue, memory, llm_client, ...) -> OperationResult
async def handle_reflect(op, *, agent, memory, llm_client, ...) -> OperationResult
async def handle_score_importance(op, *, memory_event, llm_client, ...) -> OperationResult
```

每个 handler：
- SHALL 调一次 LLM（除 score_importance 可能批 ≤ 5 events 一调）
- SHALL 不直接 mutate AgentRuntime / Ledger / Atlas（只返回 OperationResult，主线程消费）
- SHALL 处理 LLM 失败：返回 `OperationResult(success=False, error_msg=...)` 不抛异常
- SHALL 记录 token usage（prompt_tokens / completion_tokens / model）供 cost telemetry

#### Scenario: handler 失败不阻塞

- **WHEN** llm_client.generate 抛异常 in handle_do_something
- **THEN** 返回 OperationResult(success=False, error_msg="...") 不抛；agent 下 tick 仍能决策（pending_operation 清空）

### Requirement: 顶层 API re-export

`synthetic_socio_wind_tunnel/agent/operations/__init__.py` SHALL re-export `PendingOp` / `OperationResult` / `OperationPool`。
顶层 `synthetic_socio_wind_tunnel/__init__.py` SHALL 同步 re-export `OperationPool`。

#### Scenario: 顶层 import 可用

- **WHEN** `from synthetic_socio_wind_tunnel import OperationPool, PendingOp`
- **THEN** SHALL 不抛 ImportError

### Requirement: tier LLM 路由

`OperationPool` 构造参数 SHALL 接受 `llm_routing: dict[OpKind, str]`：

```python
DEFAULT_TIER = {
    "do_something": "sonnet",          # 行为决策需要好模型
    "generate_message": "sonnet",       # 对话消息要 character 一致
    "remember_conversation": "haiku",   # 总结轻量
    "reflect": "haiku",                 # 反思轻量
    "score_importance": "nano",         # 单评分；最便宜
}
```

- 按 op.kind 选 LLMClient 实例（caller 注入 dict[tier, LLMClient]）
- 缺失 tier 时降级到 default sonnet

#### Scenario: tier 可覆盖

- **WHEN** 构造 OperationPool 传 `llm_routing={"reflect": "nano"}`
- **THEN** reflect op SHALL 使用 nano tier；其它 op 走 default

### Requirement: cost telemetry

OperationPool SHALL 暴露 `get_cost_summary() -> dict`：

```
{
    "total_ops": int,
    "by_kind": {kind: count},
    "by_tier": {tier: {prompt_tokens, completion_tokens, count}},
    "timeouts": int,
    "errors": int,
}
```

- 每 OperationResult 含 token usage 时累加到 summary
- inspector / metrics 可消费

#### Scenario: cost summary 反映真实调用

- **WHEN** 跑了 5 个 do_something（sonnet）+ 10 个 score_importance（nano）
- **THEN** get_cost_summary 返回 total_ops=15；by_tier["sonnet"].count=5；by_tier["nano"].count=10
