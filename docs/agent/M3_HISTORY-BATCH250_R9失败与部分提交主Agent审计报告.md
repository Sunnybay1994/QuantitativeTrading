# M3 HISTORY-BATCH250 R9 失败与部分提交主 Agent 审计报告

## 结论

- 项目 CLI 在约 `335.7s` 后返回 `G1_WORKFLOW_EXECUTION_FAILED/HISTORY`；不补跑本批余额。
- CLI 返回后 WSL 进程检查为空，确认写者静默后才执行终态审计。
- 冻结的 250 个 identity 中前 `102` 个完整提交，第 `103` 个留下合法 intent-only。
- 错误已脱敏，不能据此断言限流、网络或服务端根因。

## 静默态生产审计

- history `3186`、verified `1579`、missing `1606`、partial `1`
- `1579 + 1606 + 1 = 3186`
- endpoint：`adj_factor=330`、`daily=330`、`dividend=291`、`index_daily=1`、`stk_limit=324`、`suspend_d=303`
- 唯一 partial：
  - request id：`837804b49c95606e52f9f99fc81ebc544039dee84de65f02e2fb4c62a2250a1d`
  - endpoint/symbol/window：`daily/600426.SH/20151009..20260710`
  - journal：仅 `intent.json`
  - raw：`ABSENT`
- 所有完整 receipt 均通过生产验证；无孤儿 raw 或第二个 partial。

