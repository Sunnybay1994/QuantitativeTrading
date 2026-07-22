# M3 HISTORY-BATCH250 真实恢复执行与主 Agent 验证报告

日期：2026-07-18  
任务单：[`M3_HISTORY-BATCH250真实恢复执行任务单.md`](M3_HISTORY-BATCH250真实恢复执行任务单.md)  
状态：**通过**；HISTORY/G1/M3 Gate 仍未完成

唯一网络命令 `history --max-new-requests 250` 只执行一次，exit 0，约 399.6 秒；CLI 报告 `new_requests_committed=250`、`completed_stages=[INDEX]`、`outcome=INCOMPLETE`、无错误码。未并发 writer、未改 request rate/policy、未启动其他阶段。实际 attempts 不可独立证明，只报告最多 1,250 的合同上限。

零网络生产 status exit 0。随后逐条使用 `verify_tushare_receipt` 和 `RawStore.inspect_request_state()` 验证：

| 指标 | 前 | 后 | 增量 |
|---|---:|---:|---:|
| total | 3186 | 3186 | 0 |
| verified reusable | 249 | 499 | +250 |
| missing | 2937 | 2687 | -250 |
| planned partial | 0 | 0 | 0 |

endpoint 总计 `adj_factor=95, daily=101, dividend=102, stk_limit=103, suspend_d=98`，增量精确等于冻结的 `47/51/48/45/59`。计划外目录仍为 132 complete + 1 partial，即 127 INDEX + 旧月窗 5 complete / 1 partial。

按用户 24 小时流程简化，本批由主 Agent 直接执行验证，未调用外部 Agent，不声称外部独立初验。HISTORY 尚缺 2,687，仍不得声明任何后续 Gate 完成。
