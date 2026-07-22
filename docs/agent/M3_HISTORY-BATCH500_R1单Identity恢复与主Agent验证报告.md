# M3 HISTORY-BATCH500 R1 单 Identity 恢复与主 Agent 验证报告

## 结论

- 状态：**通过**。
- 恢复命令只执行一次：
  `python -m quant.research.m3.run_g1 --config configs/research/m3_qlib_example.toml history --max-new-requests 1`
- 命令退出码为 `0`，新增提交 `1` 个请求；工作流保持 `[INDEX]/INCOMPLETE`，未生成或发布候选产物。
- 恢复后的零网络生产收据验证结果为：history 总数 `3186`、已验证 `573`、缺失 `2613`、partial `0`。

## 恢复对象

- request id：`31aac841cebc9bc2e3197b1aa0d49664407a92a1fd9a8577c7b32faa7d32bb13`
- endpoint：`adj_factor`
- symbol/window：`600884.SH`，`20151009..20260710`
- 恢复前仅存在合法 canonical intent；raw bundle 与 receipt 均不存在。

## 验证证据

1. `status` 零网络检查退出码为 `0`，返回 `completed_stages=["INDEX"]`、`outcome="INCOMPLETE"`。
2. 对确定性 history plan 的全部 `3186` 个 identity 逐项检查：
   - 有 receipt 时调用生产 `verify_tushare_receipt`，重验 intent/receipt/raw metadata/raw parquet/content hash 与 endpoint policy；
   - 无 receipt 时调用 `RawStore.inspect_request_state`，并联合检查 journal request 目录；
   - 未发现孤儿 raw、intent-only、空目录或其他 partial 状态。
3. 已验证 endpoint 分布：
   - `adj_factor=109`
   - `daily=117`
   - `dividend=116`
   - `stk_limit=118`
   - `suspend_d=113`

## 风险与后续约束

- BATCH500 的原始失败被工作流按契约脱敏为 `G1_WORKFLOW_EXECUTION_FAILED`；现有证据不能证明具体外部原因，不将其表述为限流、网络或服务端故障。
- 单请求恢复耗时约 `195.9s`，说明外部响应可能显著变慢。后续批量上限降回 `100`；继续遵守单写者、冻结 identity 顺序、失败即停且不补跑余额。
- HISTORY 尚未完成，M3 G1 Gate 未通过。

