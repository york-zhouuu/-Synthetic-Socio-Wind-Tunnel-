# Tasks — thesis-focus

本 change 为 docs-only 收敛。不改代码、不改 spec、不跑测试。

## 1. Canonical thesis 文件

- [ ] 1.1 创建 `docs/agent_system/00-thesis.md`
  - 一句话 thesis
  - 主边界定义 + 可测量变量
  - 四层机制链图 + 每层的位置 / 测量 / 对应能力
  - Chain-Position 门禁条款（供 Phase 2 change 引用）
  - smoke demo 证据锚（2026-04-21，delta +302m）
  - "什么不再做"（四重边界降级表）
  - "产品外溢"章节（原 Brief 的政策接口 / 参与式 / 反哺现实）

## 2. 顶层文档同步

- [ ] 2.1 `README.md`：把 "Four invisible boundaries stack on top of each other"
  表格替换为 "Main boundary + three mechanism layers"，并加一行引用指向
  `docs/agent_system/00-thesis.md`
- [ ] 2.2 `docs/项目Brief.md` §3：新增 "v2 Thesis 收敛" 章节置顶，v1 §3.2
  "本项目定义的四重边界"改名为 "Appendix A — v1 开题期的四重边界表述"，
  并在顶部加入 v1→v2 对照说明
- [ ] 2.3 `docs/WIP-progress-report.md` Page 2：把 "边界分类框架" 改为
  "一主三机制链"，保留 Schelling / Stanford / Replica 三 precedent 不动
- [ ] 2.4 `CLAUDE.md` Project Overview 一句话：从 "研究'超在地性边界渗透'"
  改为 "研究 Attention-induced Nearby Blindness（注意力位移制造的附近性
  盲区）及其反向干预"

## 3. openspec 文档同步

- [ ] 3.1 `openspec/README.md`：顶部加入 "Project Thesis" section，引用
  `docs/agent_system/00-thesis.md`
- [ ] 3.2 `openspec/changes/phase-2-roadmap/proposal.md` `## Why`：把
  "完成'超在地性边界渗透'实验" 改写为 thesis chain 语言，说明七块能力
  各自在链条上的位置
- [ ] 3.3 `openspec/changes/phase-2-roadmap/tasks.md` 前置说明：新增
  "**Chain-Position 门禁**"段，与现有 fitness-report 门禁并列

## 4. 设计文档同步

- [ ] 4.1 `docs/agent_system/03-干预机制与实验指标.md`：在文件顶部加一段
  "干预 → 机制链位置"映射表（五类干预都在 `algorithmic-input` 层，
  通过 attention-main 生效），其余内容保留

## 5. 验证

- [ ] 5.1 grep 检查："四重边界 | four invisible boundaries" 只在
  `docs/项目Brief.md`（Appendix A） 和 00-thesis.md（降级表） 中出现
- [ ] 5.2 grep 检查："Chain-Position | attention-main | spatial-output |
  social-downstream" 在 00-thesis.md 和 phase-2-roadmap 中可被找到
- [ ] 5.3 Read 00-thesis.md 全文自检：链图 / 门禁 / 证据三个区块齐全
