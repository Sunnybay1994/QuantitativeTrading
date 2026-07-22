# M3 HISTORY-BATCH500 失败与部分提交主 Agent 审计报告

日期：2026-07-18  
任务单：[`M3_HISTORY-BATCH500真实恢复执行任务单.md`](M3_HISTORY-BATCH500真实恢复执行任务单.md)  
状态：**批次失败，已提交证据可复用；不得表述为 BATCH500 通过**

## 现象

唯一命令 `history --max-new-requests 500` 运行约 221.2 秒后 exit 1：

```text
error_code=G1_WORKFLOW_EXECUTION_FAILED
error_operation=HISTORY
outcome=FAILED
```

CLI 失败结果没有可信的 committed 数，因此未使用 CLI 的 `0/null` 字段推断实际进度，也未补跑余额。

## 零网络审计

生产 `status` 随后 exit 0，journal 仍为可恢复 `[INDEX]/INCOMPLETE`。逐条 `verify_tushare_receipt` 与 raw state 检查得到：

```text
verified_reusable = 572
missing = 2613
planned partial = 1
```

相对 baseline 499 verified / 2687 missing / partial 0：成功提交 `k=73`，并在第 74 个目标留下一个 partial。守恒：`2687 - 2613 = 73 + 1`。

verified endpoint 总计：

```text
adj_factor=108, daily=117, dividend=116, stk_limit=118, suspend_d=113
```

相对 baseline 的 73 条成功增量为 `adj_factor +13 / daily +16 / dividend +14 / stk_limit +15 / suspend_d +15`。

## Partial 证据

失败 identity：

```text
request_id = 31aac841cebc9bc2e3197b1aa0d49664407a92a1fd9a8577c7b32faa7d32bb13
endpoint = adj_factor
ts_code = 600884.SH
start_date = 20151009
end_date = 20260710
```

受控目录只有 367-byte canonical `intent.json`；raw state=`ABSENT`，无 candidate/receipt。该状态是现有恢复合同允许的 intent-only 状态，不能计为 committed 或 complete，也不需要删除/手工修补。

## 根因与规则

- 可证根因边界：该 identity 在冻结重试策略内未能产生可发布 raw/receipt，workflow 以脱敏 `G1_WORKFLOW_EXECUTION_FAILED` 停止。
- 不可证部分：安全接口不保留/输出供应商底层 cause，不能判定究竟是 rate-limit、网络、服务端、空响应拒绝或永久业务错误；报告不得猜测。
- 应遵循规则：BATCH500 不重跑余额；保留 73 个 verified receipts 与 intent-only partial；另立单 identity 恢复任务，以最小预算验证该请求能否恢复。
- 最小复现：在 production status 可恢复、partial 精确为上述 identity 的条件下执行 `history --max-new-requests 1` 一次。
- 新增测试：本次没有生产代码变化，不新增为凑数的测试；intent-only 重试、失败即停和 receipt 复用已有单元测试覆盖。
- 通过条件：单 identity 产生并通过 receipt，状态变为 573 verified / 2613 missing / partial 0；若再次失败则停止，不扩大批次，并记录重复阻塞证据。

按用户 24 小时流程简化，本审计由主 Agent 直接执行，未调用外部 Agent，不声称外部独立初验。
