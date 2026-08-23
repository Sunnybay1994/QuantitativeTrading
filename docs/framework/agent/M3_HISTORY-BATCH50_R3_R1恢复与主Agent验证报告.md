# M3 HISTORY-BATCH50 R3 R1 恢复与主 Agent 验证报告

## 结论

- 唯一恢复命令退出码 `0`，`new_requests_committed=1`。
- request `3930f7579318ce43a6b9f22853ef28bba3dcc452b4f75f35750a164bae91420d`（`stk_limit/688506.SH`）已生成并通过生产 receipt/raw/content 验证。
- 静默态全量结果：history `3186`、verified `677`、missing `2509`、partial `0`。
- endpoint：`adj_factor=133`、`daily=136`、`dividend=131`、`stk_limit=142`、`suspend_d=135`。
- 工作流仍为 `[INDEX]/INCOMPLETE`；未进入 candidate、prepare 或 publish。

## 剩余风险

- 失败原因仍被生产契约脱敏，不能从恢复成功反推原因为限流、网络或服务端错误。
- 单 identity 恢复耗时约 `163.7s`，继续采用更小批次，并在任何失败后先确认写者静默。

