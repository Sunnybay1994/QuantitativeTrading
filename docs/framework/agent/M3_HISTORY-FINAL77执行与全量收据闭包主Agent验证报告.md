# M3 HISTORY-FINAL77 执行与全量收据闭包主 Agent 验证报告

## 结论

- FINAL77 的外层等待在约 20 分钟后 timeout，但 WSL 写者仍存活；主 Agent 按 `.ai/coding_rules.md` §9 只监控原 PID，没有重跑或启动第二写者。
- 原写者最终自行退出，进程树静默。
- 生产 `_verify_tushare_complete` 已验证全部 HISTORY identity：`3186/3186`。
- endpoint 闭包：`adj_factor=637`、`daily=637`、`dividend=637`、`index_daily=1`、`stk_limit=637`、`suspend_d=637`。
- 无 missing、无 partial、无孤儿 raw；FINAL77 数据回填完成。

## Gate 边界

- workflow 随后进入候选构建并返回 `G1_WORKFLOW_QUALITY_FAILED/CANDIDATE`，所以不能把整个 G1 workflow 或 M3 Gate 标记通过。
- 绕过顶层异常折叠的定向 traceback 首先定位到 `apply_adjustment_factors_strict` 的错误 key 全等约束；该问题已在独立任务中修复并验证。
- factor 修复后，下一阻断为真实 `H00300.CSI` benchmark 的 close-only 历史与 OHLC 标签契约冲突；见独立设计阻断记录。

