# D1' DeepSeek smoke 结果记录

**跑时间**：2026-05-11 13:27 → 17:26（4 小时整）
**配置**：1 seed × 14 day × 100 agent × 4 variant × DeepSeek (v4-pro / v4-flash) + ai-town path
**suite_dir**：`data/experiments/20260511_132735_d1_deepseek_nothink_smoke/`

## 关键开关

DeepSeek `v4-pro` 是 **reasoner 模型**（默认会先 chain-of-thought 思考 5-10 倍 token 后再答），跑了一次 thinking-on 的 D1 12+ 小时还没结束。**第二次跑前关掉 thinking**，参数：

```python
extra_body={
    "thinking": {"type": "disabled"},      # 主开关（实测 7.7s → 1.7s）
    "enable_thinking": False,              # 兜底（不同 DeepSeek 变体可能识别不同 flag）
}
```

效果：**单 op 时间从 7.7s → 1.7s（4.3x 提速）**，full smoke wall 从 12+hr → 4hr。

## 主要指标（vs 之前 D1 Gemini）

| Variant | Encounter total | vs baseline | traj_dev (protag) | traj_dev (all) | replan |
|---|---|---|---|---|---|
| baseline | 1,195,331 | — | None | None | 0 |
| hyperlocal_push | 1,181,146 | **−1.2% ⚠️** | **187.9** | 139.2 | 64 |
| global_distraction | 1,126,258 | −5.8% | **232.0** | 187.9 | 44 |
| phone_friction | 1,280,302 | **+7.1% ✅** | None | None | 143 |

vs **D1 Gemini 同配置**：
| | DeepSeek (nothink) | Gemini Flash |
|---|---|---|
| baseline encs | 1.20M | 1.05M |
| hp vs baseline | **−1.2%** | **+4.4%** |
| gd vs baseline | −5.8% | −3.8% |
| pf vs baseline | **+7.1%** | **+11.8%** |
| traj hp < gd | ✅ 188 < 232 | ✅ 128 < 189 |
| Op errors | 1/1069 (0.1%) | 4800/5305 (90%) |
| Wall | 4 hr | 96 min |
| Cost | ~$0.3 (估) | $3.30 |

## 判读

**好消息**：
1. **DeepSeek 没 quota 问题**（1/1069 errors vs Gemini 90%）。30 seed 跑下来不会被 429 打死。
2. **传统 paired mirror 验证持续工作**：traj_dev hp (188) < gd (232)，与 Gemini 同方向。
3. **pf +7.1% 仍 consistent**：friction nudge 推人出门效应延续。
4. **DeepSeek cost ~$0.3 vs Gemini $3.30**：**便宜 10 倍**。15 seed × $0.3 = ~$5 总 cost。

**值得注意的（不一定是问题）**：
1. **hp 方向 -1.2%** vs Gemini +4.4% — 1 seed 信号小，可能是 noise。15 seed CI 会回答：
   - 如果 D2 hp 在 [-3%, +3%] 区间，是 noise，thesis 弱信号
   - 如果 D2 hp CI 含 +0% 但偏正，仍支持 thesis
   - 如果 D2 hp CI 含 0 且对称，thesis null
2. **traj_dev_m_subset 反而 < traj_dev_m_all** —— 不寻常但可能正常：10 protag 远离 hp target（被推后 plan 改了），90 scripted 反而留在 hp 推送地附近 dwell。需要在 D2 看是否稳定。

## Provider metadata

- `provider`: `deepseek`
- `model_version`: `deepseek:v4-pro+v4-flash`
- `code_commit`: 见 `seed_42.json` 内 `reproducibility_lock.code_commit`

## 下一步

直接 launch **D2 15 seed × 14 day × 100 agent × DeepSeek (nothink) × 4 variant**：
- 预估 wall：**60 小时 = 2.5 天**（D1 4hr × 15）
- 预估 cost：**~$5-10**

D2 完成后写第二份 doc。
