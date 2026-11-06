# 归档：2026-07 至 2026-09 多 Agent 分层治理期

本目录保存项目在 2026-07-11 至 2026-09-08 期间采用"用户 → 统筹 Agent → 领域经理 → Worker → 独立审查者"
分层治理模式时产生的全部流程文档。**它们只用于查历史，不再是任何有效规则、任务或状态。**
2026-09-08 起项目改为单 Agent、业务优先模式，有效规则见根目录 [`AGENTS.md`](../../../AGENTS.md)，
当前工作见 [`项目实施路线图.md`](../../../项目实施路线图.md)。

归档原因与证据见 [`docs/项目审查与流程重构报告_20260908.md`](../reviews_2026-09/项目审查与流程重构报告_20260908.md)。

## 目录

| 子目录/文件 | 原位置 | 内容 |
|---|---|---|
| `AGENTS_v1_20260908.md` | `/AGENTS.md` | 旧准则（25KB，四层架构、资源租约、Gate 体系） |
| `项目实施路线图_v3_20260813.md` | `/项目实施路线图.md` | 旧 M0–M5 路线图；M0/M1/M2 的验收证据和数字仍可在此查阅 |
| `正式产物身份、数据溯源与可复现性方法论.md` | 根目录 | receipt/manifest/fresh verifier 方法论 |
| `ai_通用Agent操作系统/` | `/.ai/` | 通用 Agent 规则、审查清单、多 Agent 交付工作流 |
| `governance/` | `docs/governance/` | 多 Agent 治理规范、CODEX_HANDOFF（73KB 状态快照）、用户待批示清单（90KB）、合流治理路线图 |
| `framework/` | `docs/framework/` | 约 1,060 份 M1/M3/M4 任务书、交付、审查、主 Agent 验收报告；M3 实施与交接（235KB） |
| `research/tasks|deliveries|reviews|agent|roadmaps|reports` | `docs/research/…` | 投研线任务书/交付/审查/旧路线图/进展报告 |
| `gui/` | `docs/gui/` | Streamlit GUI 设计与运维手册（已冻结） |

归档文档内部的相对链接大多指向旧路径，**不修复**；需要时按上表映射手工定位。

## 仍有参考价值的内容（按需查）

- 数据层的真实数字（Tushare bulk 快照行数、ETF 总回报构造口径、财务采集 177,184 请求）：
  见 `项目实施路线图_v3_20260813.md` M1/M2 节和 `governance/CODEX_HANDOFF.md` 顶部几节。
- 各因子/策略假设的真实 run 结论：已迁至 [`docs/research/hypotheses/`](../../research/hypotheses)，不在本目录。
- audit-v4 唯一阻断为 1 条 `FINA_INDICATOR_END_AFTER_AVAILABLE` 记录：见 `research/reports/M2_近期策略研究进展与后续工作安排_20260830.md` §3。
