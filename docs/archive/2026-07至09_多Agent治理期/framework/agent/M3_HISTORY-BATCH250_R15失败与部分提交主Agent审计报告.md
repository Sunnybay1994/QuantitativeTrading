# M3 HISTORY-BATCH250 R15 失败与部分提交主 Agent 审计报告

## 结论

- 项目 CLI 在约 `387.5s` 后返回 `G1_WORKFLOW_EXECUTION_FAILED/HISTORY`；不补跑余额。
- 写者静默后全量审计证明：冻结前缀 `28` 个完整提交，第 `29` 个 intent-only。
- 错误已脱敏，不能推断具体外部根因。

## 终态证据

- history `3186`、verified `2858`、missing `327`、partial `1`
- `2858 + 327 + 1 = 3186`
- endpoint：`adj_factor=575`、`daily=579`、`dividend=577`、`index_daily=1`、`stk_limit=576`、`suspend_d=550`
- partial：`e77989adb2e3210da57ad6728a6cdb862ee1cb4ae928f977cb286ad4c54ec74f`
  （`suspend_d/300251.SZ/20151009..20260710`），journal 仅 `intent.json`，raw `ABSENT`。
- 所有完整 receipt 均通过生产验证；无第二个 partial 或孤儿 raw。

