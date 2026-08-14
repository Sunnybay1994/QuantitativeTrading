# Agent 工作记录

本目录保存仍需直接查阅的任务、审批与工程证据。历史文件保留审计价值，但不自动代表当前状态或当前执行入口。

## 当前入口

- 用户决策、授权、外部材料和真实运行窗口：[`用户待批示与参与事项.md`](用户待批示与参与事项.md)
- 项目当前阶段与完成标准：[`../../项目实施路线图.md`](../../项目实施路线图.md)
- 跨任务续写摘要：[`../CODEX_HANDOFF.md`](../CODEX_HANDOFF.md)
- M3 契约与交接：[`../M3实施与Agent交接.md`](../M3实施与Agent交接.md)
- 正式产物方法论：[`../../正式产物身份、数据溯源与可复现性方法论.md`](../../正式产物身份、数据溯源与可复现性方法论.md)

截至 2026-08-14，前台优先级是策略研究与首个 `PAPER_CANDIDATE`；`UA-M4-004` 已批准，M4 的 Windows formal gateway、store、service composition、verified schedule 与只读 daily runner 已完成，现等待真实候选与开盘事实。M3 修正 revision 的 honest 300 h5/h10 三场景 backtest 已完成，但 retained fold plan 只有一个 fold，正式跨折 `research-summary` 因最小 two-fold 合同 fail-closed；该 root 不进入 tracking/acceptance。下一后台包复用现有 G1 release，从延长一个 session 的新配置派生 two-fold × two-horizon 链。Linux/ext4、真实 PAPER 运行和 28 日 soak 仍未完成。

## 归档规则

- 已被最终报告取代、且不再作为执行入口的任务书、Prompt 和阶段协调材料移入 [`../archive/agent-history/`](../archive/agent-history/)。
- 实现、初验、返工和主验报告默认保留原路径，避免破坏审计链；只有成组迁移并同步修正引用时才移动。
- 临时日志、pytest basetemp、诊断目录和已合流 worktree 不属于长期文档，完成后删除；需要保留的运行证据移入 `artifacts/archive/`。
- 过程报告不得自行宣布里程碑或 Gate 通过；以路线图、代码、测试和可重现产物为准。
