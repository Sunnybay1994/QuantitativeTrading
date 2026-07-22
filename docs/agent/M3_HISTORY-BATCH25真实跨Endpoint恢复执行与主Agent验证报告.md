# M3 HISTORY-BATCH25 真实跨 Endpoint 恢复执行与主 Agent 验证报告

日期：2026-07-18  
执行与验证角色：主 Agent  
任务单：[`M3_HISTORY-BATCH25真实跨Endpoint恢复执行任务单.md`](M3_HISTORY-BATCH25真实跨Endpoint恢复执行任务单.md)  
状态：**BATCH25 执行与验证通过**；HISTORY/G1/M3 Gate 仍未完成

## 1. 授权与流程边界

- 用户明确批准 M3 HISTORY/G9 API 预算，并随后授权后续 Tushare API 由主 Agent 按 2000 积分权限和端点限频自行统筹，不再逐批请求批准。
- 本批仍严格执行已冻结的 `max_new_requests=25`，不把授权解释为无界请求。
- 用户 24 小时流程简化仍有效：本批由主 Agent 直接执行、审查与验证，未调用外部 Cursor Agent，也不声称完成外部独立初验。
- 未读取、输出、复制或记录 token；未启动 REFERENCE/PREPARE/PUBLISH/run-all。

## 2. 唯一真实网络命令

只执行一次：

```text
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 25
```

结果：exit 0，约 170 秒：

```json
{
  "command": "history",
  "completed_stages": ["INDEX"],
  "history_requests": 3186,
  "history_symbols": 637,
  "max_new_requests": 25,
  "new_requests_committed": 25,
  "outcome": "INCOMPLETE",
  "error_code": null
}
```

实际 API attempt 数不能由 receipt 独立反推；可证明边界是单次命令、25 个 committed identity、冻结配置每 identity 最多 5 attempts，因此合同上限为 125 attempts。本报告不把上限写成实际次数。

## 3. 零网络生产验证

随后执行：

1. 生产 `run_g1 status`：exit 0，`completed_stages=[INDEX]`、`outcome=INCOMPLETE`、`history_requests=3186`。
2. 对 HISTORY 计划中每个现有 receipt 调用生产 `verify_tushare_receipt`，重验 spec/request/raw identity、endpoint policy、raw bytes/metadata/content digest 闭包。
3. 对无 receipt identity 使用 `RawStore.inspect_request_state()` 区分真正 missing 与 planned partial。

验证结果：

| 指标 | 执行前 | 执行后 | 增量 |
|---|---:|---:|---:|
| HISTORY plan total | 3186 | 3186 | 0 |
| verified reusable | 124 | 149 | +25 |
| missing | 3062 | 3037 | -25 |
| planned partial without receipt | 0 | 0 | 0 |

计数守恒：`149 - 124 = 25`，`3062 - 3037 = 25`，与 CLI `new_requests_committed=25` 一致。

执行后 verified endpoint 总计：

```text
adj_factor=30
daily=39
dividend=25
stk_limit=30
suspend_d=25
```

相对执行前增量正好是任务书冻结分布：adj_factor +2、daily +3、dividend +4、stk_limit +1、suspend_d +15。

HISTORY 计划外 journal 目录为 132 complete + 1 partial；其中 127 个 complete 是已验证 INDEX receipts，扣除后旧式无 `ts_code` 月窗仍为 5 complete + 1 partial，未被覆盖或错误计入 HISTORY reusable。

## 4. 后续有界计划

当前前 25 个 missing identity 的集合摘要与 endpoint 分布已经零网络派生：

```text
identity set sha256 = 4c75ae6e2fbf670e06066525b5899195eda9a3dede831da27c4f0126d9d0e866
adj_factor = 4
daily      = 1
dividend   = 8
stk_limit  = 10
suspend_d  = 2
```

用户已授权后续 API 由主 Agent自行统筹，因此后续不再逐批等待批准；每次仍须先冻结明确 N、identity 集合/端点分布、attempt 上限和停止条件，执行后继续逐 receipt 生产验真。不得调用已知无权限端点、并发同一 journal writer、用 sleep 绕限频或把额度耗尽表述为成功。

## 5. 剩余风险

- HISTORY 仍缺 3,037 个 identity，`HISTORY` 阶段未完成；不得声称 G1 或 M3 Gate 通过。
- 当前吞吐约 25 identity / 170 秒；后续扩大批次前必须保持 request-rate、endpoint policy 与失败即停语义，不能为赶进度放宽校验。
- 本批只覆盖 Tushare HISTORY；REFERENCE、candidate、release 及 G2–G9 的真实依赖仍未执行。
