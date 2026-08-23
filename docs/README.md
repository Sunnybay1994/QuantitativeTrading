# 项目文档导航

`docs/` 按三个业务域和一个跨域治理区组织。历史证据保留在 `archive/`，不作为当前执行入口。

## 业务目录

| 目录 | Owner | 内容 |
| --- | --- | --- |
| [`framework/`](framework/README.md) | 框架开发 Agent | 数据工程、研究框架、回测、执行、运行手册、路线图和任务证据 |
| [`research/`](research/README.md) | 投研 Agent | 研究方法、假设卡、研究结果、参考资料、路线图和任务证据 |
| [`gui/`](gui/README.md) | GUI 开发 Agent | GUI 产品设计、运维、路线图和任务证据 |
| [`governance/`](governance/README.md) | 项目架构与统筹 Agent | 多 Agent 协作、用户决策、跨任务交接、结构治理和路线图索引 |
| [`archive/`](archive/README.md) | 对应历史 owner | 已被替代但仍需审计追溯的历史材料 |

## 项目级入口

- [`../README.md`](../README.md)：项目入口、目录职责和开发命令。
- [`../A股港股通个人量化投研交易系统调研.md`](../A股港股通个人量化投研交易系统调研.md)：技术选型与架构理由 SSOT。
- [`../项目实施路线图.md`](../项目实施路线图.md)：全项目里程碑、顺序和验收标准 SSOT。
- [项目多 Agent 分层协作与资源治理规范](governance/项目多Agent分层协作与资源治理规范.md)：角色、任务下发、资源锁和 worktree 生命周期。
- [跨任务交接](governance/CODEX_HANDOFF.md)：稳定合流点、环境边界、阻断与恢复入口。
- [路线图索引](governance/roadmaps/README.md)：三个业务域与项目结构治理路线图入口。

## 文档治理

- 代码、配置和文档遵循根目录 [`AGENTS.md`](../AGENTS.md) 的 SSOT 与同步规则。
- 每个业务域的 `agent/` 只保存该域任务书、交付、初验和主验记录；它们是过程证据，不自动改变 Gate。
- 跨域协作、用户裁定和全局交接只进入 `governance/`，不得复制到三个业务目录。
- 投研参考资料是知识输入，不等于已验证项目结论；项目状态只由代码、测试、配置、路线图和不可变产物证明。
- `archive/` 不是当前实现依据；与当前 SSOT 冲突时以 SSOT 为准。
