# DeepSeek API 错误码对照（官方）

来源：DeepSeek platform 错误码文档（用户提供，2026-05-16）。

| HTTP code | 含义 | 原因 | 解决方法 |
|---|---|---|---|
| **400** | 格式错误 | 请求体格式不对 | 看 error msg 改 request body |
| **401** | 认证失败 | API key 错或缺失 | 检查 key / 重新创建 |
| **402** | 余额不足 | 账户余额负 | 上 platform 充值 |
| **422** | 参数错误 | 请求体里某个参数值不合法 | 看 error msg 改参数 |
| **429** | 请求速率达上限 | RPM (Requests Per Minute) 或 TPM (Tokens Per Minute) 超限 | 降速或加 key |
| **500** | 服务器故障 | DeepSeek 内部 bug | 等一下重试；持续就联系他们 |
| **503** | 服务器繁忙 | DeepSeek 负载过高 | 稍后重试 |

## 我们 `RetryPolicy.classify` 的归类（已正确）

`synthetic_socio_wind_tunnel/run_resilience/retry.py` 当前归类：

```python
retryable_http_statuses = (408, 425, 429, 500, 502, 503, 504)
fatal_http_statuses     = (400, 401, 403, 404, 422)
```

跟 DeepSeek 的错误码表完美对齐：
- **429 / 500 / 503 → retryable**：等等再来 ✓
- **400 / 401 / 422 → fatal**：参数 / 认证 / 格式错，retry 没用 ✓
- **402（余额不足）SHALL fatal 但当前归 unknown**——retry 也救不了，建议加进 fatal 列表

## 不在这张表上的错误（我们经常看到）

| 错误类型 | 在哪一层 | 含义 | 处理 |
|---|---|---|---|
| `APIConnectionError` | openai SDK 包装层 | TCP / TLS / DNS / 连接被重置——**请求根本没到 DeepSeek server** | RetryPolicy 归类为 `retryable`（默认）|
| `APITimeoutError` | openai SDK | 连接超时 | retryable |
| `httpx.ConnectError` | httpx 底层 | 同上 | retryable |
| `httpx.ReadError` | httpx 底层 | server 中途 close 连接 | retryable |

**关键诊断启发**：
- 看到 **429** = 我们打太猛、改 RPM 或加 key
- 看到 **503** = DeepSeek 当前负载高，等等
- 看到 **APIConnectionError** = 网络层问题（不是 DeepSeek 限速），可能是：
  - DeepSeek 服务器某个时段抽风
  - 我们 client 的连接策略（如 keepalive=0 高频建连）触发某种限制
  - 本地网络抖动

## 建议补全 fatal_http_statuses

```python
# 在 retry.py 里：
_DEFAULT_FATAL_HTTP: tuple[int, ...] = (400, 401, 402, 403, 404, 422)
#                                            ^^^ 加 402 余额不足
```

402 是"账户余额耗尽"，retry 不会解决，应该立即 raise 让上层 abort + 通知用户充值。

---

存档于：2026-05-16，run-resilience + tick-level-resume archive 后的运维实战阶段
