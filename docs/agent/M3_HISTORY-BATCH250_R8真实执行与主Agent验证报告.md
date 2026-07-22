# M3 HISTORY-BATCH250 R8 真实执行与主 Agent 验证报告

## 结论

- 唯一命令退出码 `0`，新增提交 `250`，耗时约 `460.5s`。
- 静默态全量生产验证：history `3186`、verified `1477`、missing `1709`、partial `0`。
- endpoint：`adj_factor=305`、`daily=308`、`dividend=272`、`index_daily=1`、`stk_limit=307`、`suspend_d=284`。
- HISTORY 内唯一 `index_daily` receipt 已按其生产 policy 通过；未混入 INDEX stage 的 127 张 index_weight 计数。
- 工作流仍为 `[INDEX]/INCOMPLETE`，未构建或发布候选。

