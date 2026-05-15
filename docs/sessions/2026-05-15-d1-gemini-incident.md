# D1' Gemini 全量 run · 2026-05-15 事故复盘

## TL;DR

2026-05-14 15:29 启动的 D1' 全量(1000 agent × 14 day × 4 variants × 1 seed
× workers=4 × Gemini 3.1 Flash Lite),跑到 5-15 中午发现 **3 个 worker 因
google-genai async client + httpx 连接池死锁卡死,7+ 小时无进展**。 5-15
17:00 手动 kill 3 个死 worker,保住 phone_friction(唯一还活着的)继续跑。

**直接损失**: 24 小时 wall time × 3 variant ≈ 72 计算小时。0 个 seed JSON
落地(死锁发生在 dump 之前)。

**长期影响**: 暴露 google-genai SDK 的 scale-only bug;为后续 Gemini 大尺度
run 提供修复方案。

---

## 时间线

| Time (2026-05-14/15) | 事件 |
|---|---|
| 14:29 | 用户授权"跑吧,然后做好监控" |
| 14:29 | 启动 4-worker 并行 run, pid 42724 coordinator + 42814-42817 workers |
| 15:30 | 4 worker 通过 `[aitown] wired` setup 完成,进入主模拟循环 |
| 5-15 早上 | 进度: baseline 50%, gd 43%, hp/pf 36% (用户首查) |
| 5-15 11:47-12:46 | **3 个 worker (baseline/hp/gd) log 输出突然停滞** |
| 5-15 15:00 | 用户复查发现"3 worker 7h 无新 log",启动诊断 |
| 5-15 16:00 | 确认 3 worker 死锁,1 worker (pf) 仍活 |
| 5-15 17:00 | SIGKILL 3 个死 worker,保 pf 继续跑 |

---

## 现象 vs. 根因

### 表层现象

| 指标 | baseline | gd | hp | pf |
|---|---|---|---|---|
| 最后 log 时间 | 11:47 | 12:46 | 11:47 | 18:18 (still active) |
| 静默时长 | 7h | 6h | 7h | 30 min |
| 完成天数 | 11/14 | 9/14 | 6/14 | 6/14 |
| ESTABLISHED TCP | 0 | 0 | 0 | 31 |
| CLOSE_WAIT TCP | 43 | 2 | 2 | **2212** |
| 进程 state | UN | RN | UN | UN |
| CPU % | 21 | 32 | 25 | 16 |
| RSS | 240MB | 1190MB | 462MB | 77MB(后涨) |
| seed JSON 落地 | 0 | 0 | 0 | 0 |

### 根因三连

```
[原因 1] Gemini 服务端关闭老 TCP 连接
   └ 长连接 idle timeout / LB 轮换 / keepalive 上限
   ↓
[原因 2] google-genai async SDK 不正确处理 FIN
   └ 底层 httpx async transport 在 macOS kqueue 下
     某些边缘 case 没把 socket fd 标记为 "broken"
   └ 这些 fd 留在 httpx 连接池里, 状态 CLOSE_WAIT
   └ 池子从外部看 "有可用连接", 实际全是死的
   ↓
[原因 3] 连接池毒化 → 拿 slot 永远拿不到 → 死锁
   └ 新的 LLM call 想从池子拿 slot, 拿不到
   └ asyncio.wait_for(120s) 取消单个 task, 但池子状态不变
   └ 下一个 task 还是拿不到, 还是被取消
   └ 整 worker 进入"取消 → 重试 → 取消"无限循环
   └ 表现: CPU 持续 20-30%, 但 0 LLM 输出, log 静默
```

### 为什么 `asyncio.wait_for(120s)` 救不了

`wait_for` 取消的是**单个 await**,被取消后:
- 上层 task 抛 `CancelledError`,看起来"快速失败"
- 但底层 socket fd **仍然**留在 CLOSE_WAIT
- 下一个 task 从同一个被毒化的连接池拿 slot,继续死锁

我们的 timeout 设计能防"<u>单 call 永远不返回</u>"(D1' 第一轮 DeepSeek 那个 30
min hang 场景),但**不能防"连接池毒化导致全 worker 拿不到 slot"**。

### 为什么 phone_friction 没死(暂时)

pf 这个 variant **不做 push delivery**——它只调低手机吸引力,不发推送,
不触发 protag 对推送的响应决策。

per-tick LLM 调用量约为 hp/gd 的 1/3。连接池被毒化速度也按比例慢:

| Variant | 每天 LLM call 估算 | CLOSE_WAIT 累积速度 |
|---|---|---|
| hp | ~10000 (5 push × 200 protag × ... ) | 快(撞死锁早) |
| gd | ~10000 | 快 |
| baseline | ~3000 (只有 do_something) | 中等 |
| pf | ~3000 (只有 do_something + 弱化 attention 处理) | 中等 |

但 pf 的 CLOSE_WAIT 也在涨(28 → 2212),只是<u>没撞到饱和</u>而已。再过几小时
也会死锁,只是晚一点。

### 为什么 50-agent smoke 没测出来

| 配置 | LLM call 总量 | 连接池毒化率 |
|---|---|---|
| 50-agent × 1d smoke | ~30k | 极低,跑完都没饱和 |
| **1000-agent × 14d full** | **~10M-100M** | 几小时就饱和 |

死锁是 **scale-only bug**。我们做的所有小尺度 smoke (50/100/200 agent ×
1 day) 都触发不到。<u>下次必须加 1000-agent × 1 day full smoke</u> 作为
publishable run 前置 gate。

---

## 已做的救援

1. **17:00 SIGKILL** pid 42814(baseline) / 42815(gd) / 42816(hp)
   - 死锁状态 UN,SIGTERM 不会被接收,只能 SIGKILL
2. **pf (42817) 保留运行**
   - kill 完瞬间 pf 状态从 UN → RN(running)
   - RSS 从 400MB → 3.2GB(吃下所有释放出来的内存)
   - 真的在跑(不是死锁)
3. **coordinator (42724) 保留**
   - 它在等 ThreadPoolExecutor.map 的 4 个 subprocess 返回
   - 3 个 worker 已 kill → 立即返回 fail
   - 它还会等 pf 自然结束,然后 aggregate

---

## 损失

- **3 variant × 24h wall = 72 计算小时**白费
- **0 个 seed JSON 落地**(死锁发生在每个 worker 的 dump 之前)
- 等 pf 跑完估计还需 **8-12 小时**(它已 6 天/14 天,kill 释放资源后估计加速)

---

## 修复方案(已编码但未应用,见 `tools/tier_llm_factory.py`)

修复目标: 防连接池毒化。三层防御:

### Layer 1 · 关闭 keep-alive

```python
# 不允许复用任何 connection — 每次 call 用完立刻 close socket
httpx.Limits(max_connections=200, max_keepalive_connections=0)
```

代价: 每次 call 多一次 TLS handshake(~80-150ms),整体慢 10-20%。
收益: 没有 CLOSE_WAIT 累积,fd 立即释放。

### Layer 2 · 周期性回收

每 1000 次 call 主动调用 `client.aclose()` 再新建,清掉任何残留状态。

### Layer 3 · 每天 checkpoint 落盘

每模拟天结束 → dump 当前 RunMetrics 部分快照到 `seed_<N>_day<D>.partial.json`。
死锁发生时至少能从最近天恢复,不必从头跑。

### Layer 4(deferred) · 切回 sync google-genai + ThreadPoolExecutor

完全绕开 asyncio + httpx async stack。每 LLM call 用一个 thread。
优点:稳;缺点:并行度受 thread pool size 限制(默认 32)。

---

## 教训

1. **scale-only bug 不能用小尺度 smoke 排除** — 必须有 publishable 前置
   full-scale smoke (1000 agent × 1d)
2. **asyncio.wait_for 不是 connection pool 死锁的银弹** — 它只能取消
   coroutine,不能修复池状态
3. **多 worker 不能共享 LLM provider rate limit pool** — Gemini key 单
   配额 4 worker 抢,毒化叠加 4 倍速。下次需要 multi-key 轮询(像 DeepSeek)
4. **per-day checkpoint 必须** — 14-day full run 不能"全有或全无"。
   死锁/崩溃发生时至少要能恢复 N 天的部分数据
5. **process state UN 是危险信号** — 用 `lsof` + `ps -o stat` 一键查
   stuck 的脚本应该写进 `tools/audit_run_health.py`,自动跑
