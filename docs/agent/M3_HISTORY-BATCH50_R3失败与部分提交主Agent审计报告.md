# M3 HISTORY-BATCH50 R3 失败与部分提交主 Agent 审计报告

## 结论

- 项目 CLI 在约 `209.5s` 后返回 `G1_WORKFLOW_EXECUTION_FAILED/HISTORY`；本批次未通过，不补跑余额。
- CLI 返回后已检查 WSL 进程，确认无残留 `quant.research.m3.run_g1` 写者，再执行终态审计。
- 冻结的 50 个 identity 中仅前 `2` 个完整提交，第 `3` 个留下合法 intent-only；其余未开始。
- 错误按生产契约脱敏，现有证据不能证明具体是限流、网络、服务端或其他外部原因。

## 静默态生产审计

- history 总数：`3186`
- verified：`676`
- missing：`2509`
- partial：`1`
- `676 + 2509 + 1 = 3186`
- verified endpoint：`adj_factor=133`、`daily=136`、`dividend=131`、`stk_limit=141`、`suspend_d=135`
- 唯一 partial：
  - request id：`3930f7579318ce43a6b9f22853ef28bba3dcc452b4f75f35750a164bae91420d`
  - endpoint：`stk_limit`
  - symbol/window：`688506.SH/20151009..20260710`
  - journal：仅 `intent.json`
  - raw：`ABSENT`

所有已有 receipt 均通过生产 `verify_tushare_receipt`；未发现孤儿 raw 或第二个 partial。

## 恢复规则

- 只执行一次 `history --max-new-requests 1` 恢复上述 identity。
- 恢复成功前不运行新的批次；失败则保留账本并停止 API。
- 恢复后必须再次确认写者静默并全量验证达到 verified `677`、missing `2509`、partial `0`。

