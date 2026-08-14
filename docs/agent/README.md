# Agent 工作记录

本目录保存仍需直接查阅的任务、审批与工程证据。历史文件保留审计价值，但不自动代表当前状态或当前执行入口。

## 当前入口

- 用户决策、授权、外部材料和真实运行窗口：[`用户待批示与参与事项.md`](用户待批示与参与事项.md)
- 项目当前阶段与完成标准：[`../../项目实施路线图.md`](../../项目实施路线图.md)
- 跨任务续写摘要：[`../CODEX_HANDOFF.md`](../CODEX_HANDOFF.md)
- M3 契约与交接：[`../M3实施与Agent交接.md`](../M3实施与Agent交接.md)
- 正式产物方法论：[`../../正式产物身份、数据溯源与可复现性方法论.md`](../../正式产物身份、数据溯源与可复现性方法论.md)

截至 2026-08-14，前台优先级是策略研究与首个 `PAPER_CANDIDATE`；M4 已完成 Windows formal gateway、store、service composition 与 verified schedule，下一业务输入见 `UA-M4-004`。M3 honest 300 public CLI 已完整通过。Linux/ext4、真实 PAPER 运行和 28 日 soak 仍未完成。

## 归档规则

- 已被最终报告取代、且不再作为执行入口的任务书、Prompt 和阶段协调材料移入 [`../archive/agent-history/`](../archive/agent-history/)。
- 实现、初验、返工和主验报告默认保留原路径，避免破坏审计链；只有成组迁移并同步修正引用时才移动。
- 临时日志、pytest basetemp、诊断目录和已合流 worktree 不属于长期文档，完成后删除；需要保留的运行证据移入 `artifacts/archive/`。
- 过程报告不得自行宣布里程碑或 Gate 通过；以路线图、代码、测试和可重现产物为准。
