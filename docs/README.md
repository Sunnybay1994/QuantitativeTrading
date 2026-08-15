# 项目文档导航

`docs/` 根目录只保留面向项目使用者的顶层说明和当前权威入口。跨任务总体规划放在
[`roadmaps/`](roadmaps/README.md)，研究结论放在 [`research/`](research/README.md)，数据方案与质量审计放在
[`data/`](data/README.md)。实现任务书、交付报告、独立初验与主验记录统一放在
[`agent/`](agent/README.md)；已被新方案替代、仅供追溯的文档放在 [`archive/`](archive/README.md)。

## 顶层入口

- [`../README.md`](../README.md)：项目入口、目录职责与开发命令。
- [`../A股港股通个人量化投研交易系统调研.md`](../A股港股通个人量化投研交易系统调研.md)：技术选型、架构理由与候选方案 SSOT。
- [`../项目实施路线图.md`](../项目实施路线图.md)：里程碑、实施顺序与验收标准 SSOT。
- [`M3实施与Agent交接.md`](M3实施与Agent交接.md)：M3 权威契约与 Agent 交接入口。
- M3 当前实际状态以代码、路线图和 [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md) 顶部最新摘要为准；截至2026-07-31的旧总览已移入 [`archive/agent-history/`](archive/agent-history/README.md)。
- [`M3_M4实施总规划.md`](M3_M4实施总规划.md)：M3 剩余工作与 M4 的分包、依赖和交接总图。
- [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md)：2026-07-17 目录迁移停止点的全项目状态、环境、验证和恢复建议。

## 分类目录

| 目录 | 保存内容 | 不应保存的内容 |
|---|---|---|
| [`roadmaps/`](roadmaps/README.md) | 跨 session、跨任务的总体路线、阶段依赖和恢复入口 | 单次 Agent 任务书或验收报告 |
| [`research/`](research/README.md) | 因子假设、研究结果、证伪结论和前向观察合同 | 实现过程日志 |
| [`data/`](data/README.md) | 数据采集方案、字段口径、质量审计和数据就绪结论 | Agent 职责分工 |
| [`runbooks/`](runbooks/) | 可重复执行的运维与运行手册 | 一次性诊断记录 |
| [`agent/`](agent/README.md) | 单包任务书、交付、初验、主验和故障取证证据 | 总体规划、长期研究路线 |
| [`archive/`](archive/README.md) | 已被替代但仍需追溯的历史文档 | 当前执行依据 |

## 文档治理

- 代码、配置、路线图和文档必须遵循根目录 [`AGENTS.md`](../AGENTS.md) 的 SSOT 与同步更新规则。
- `agent/` 中的报告是过程证据，不替代代码、测试与可重现产物，也不自动改变路线图状态。
- 新增长期规划不得放入 `agent/`；应按主题进入 `roadmaps/`、`research/` 或 `data/`，并登记到对应目录的 `README.md`。
- `agent/` 现有历史文件不做无计划的逐文件搬迁。若需进一步瘦身，应按里程碑成组归档并同步修正全部引用，避免破坏审计链。
- `archive/` 中的文档不是当前实现依据；若与顶层 SSOT 冲突，以 SSOT 为准。
