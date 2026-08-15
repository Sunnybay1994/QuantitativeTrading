# 项目文档导航

`docs/` 根目录只保留面向项目使用者的顶层说明和当前权威入口。实现任务书、交付报告、独立初验与主验记录统一放在 [`agent/`](agent/README.md)；已被新方案替代、仅供追溯的文档放在 [`archive/`](archive/README.md)。

## 顶层入口

- [`../README.md`](../README.md)：项目入口、目录职责与开发命令。
- [`../A股港股通个人量化投研交易系统调研.md`](../A股港股通个人量化投研交易系统调研.md)：技术选型、架构理由与候选方案 SSOT。
- [`../项目实施路线图.md`](../项目实施路线图.md)：里程碑、实施顺序与验收标准 SSOT。
- [`M3实施与Agent交接.md`](M3实施与Agent交接.md)：M3 权威契约与 Agent 交接入口。
- M3 当前实际状态以代码、路线图和 [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md) 顶部最新摘要为准；截至2026-07-31的旧总览已移入 [`archive/agent-history/`](archive/agent-history/README.md)。
- [`M3_M4实施总规划.md`](M3_M4实施总规划.md)：M3 剩余工作与 M4 的分包、依赖和交接总图。
- [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md)：2026-07-17 目录迁移停止点的全项目状态、环境、验证和恢复建议。

## 文档治理

- 代码、配置、路线图和文档必须遵循根目录 [`AGENTS.md`](../AGENTS.md) 的 SSOT 与同步更新规则。
- `agent/` 中的报告是过程证据，不替代代码、测试与可重现产物，也不自动改变路线图状态。
- `archive/` 中的文档不是当前实现依据；若与顶层 SSOT 冲突，以 SSOT 为准。
