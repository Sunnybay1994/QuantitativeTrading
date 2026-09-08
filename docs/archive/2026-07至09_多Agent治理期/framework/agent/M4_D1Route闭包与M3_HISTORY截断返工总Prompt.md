# 历史外部协调 Prompt（禁止当前派发）

> 本文不得再直接粘贴给任何 Worker、subagent 或外部 Agent。下方多会话协调流程仅作历史记录；外部 Agent
> 与本地 Worker/subagent 是平级执行通道，每个最小任务必须由用户、统筹或获授权领域经理分别直接派发。

你是本轮外部总协调 Agent。请使用不同的全新 Cursor 会话并统一指定 `--model auto`，不得指定或推断具体 Grok 型号，严格执行：

`docs/framework/agent/M4_D1Route闭包与M3_HISTORY截断返工任务单.md`

开工前完整阅读：

1. `AGENTS.md`
2. `.ai/README.md`、`.ai/coding_rules.md`、`.ai/workflows/multi_agent_delivery.md`
3. `docs/framework/agent/M4_P0Route与M3_HISTORY主Agent集中验收报告.md`
4. 上述返工任务单

执行顺序必须是：

1. 全新实现 Agent 完成 D1-R；
2. 全新代码只读验收 Agent 独立初验 D1-R；失败则返工并用新会话复验，直到通过；
3. 确认 D1-R 全部写进程退出后，全新实现 Agent 完成 HISTORY-H1 的**零网络代码返工**；
4. 全新代码与 data 只读验收 Agent 独立初验 HISTORY-H1，并且只在最后运行一次零网络 status；失败则返工/复验；
5. 更新 `docs/archive/agent-history/2026-08-external-batch/M3_M4后续外部执行总报告.md` 和并发调度台账，停止并报告。

Cursor 从 Windows 启动，但所有命令必须在 WSL
`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` 使用 Miniforge `base`。禁止 Windows Python/conda，禁止初始化 Git。

本轮禁止任何 Tushare/BaoStock 网络请求，禁止执行 `history`/`run-all`，禁止删除、移动或改写现有 data、raw、
journal、receipt。HISTORY-H1 只改计划/connector 合同并验证既有 evidence 可恢复。禁止放宽 5000 行截断门禁。

只运行任务书列出的定向测试、Ruff、mypy；禁止全量 pytest，禁止 five-stage 慢测。长命令按预计完成窗口或下次
唤醒检查，不频繁轮询。

实现与验收必须是不同全新会话；验收者除唯一报告外不得写生产代码、测试或 data。每轮问题写清“现象—根因—
规则—最小复现—新增测试—通过条件”。不得勾选路线图或宣称 M3/M4/Gate 完成。

最终必须报告：

- D1 合流是否从 104/2 恢复为全部通过，定向 mypy 是否零错误；
- 新 HISTORY 计划是否为 3186，旧不变 receipt 是否复用 114，未完成 identity 是否为 3072；
- 旧 5 个完成 + 1 个失败月窗 suspend evidence 是否原样保留；
- 一句可供用户决定的新版 HISTORY 授权建议。

完成后停止，不启动网络阶段，等待主 Agent 验收和用户授权。
