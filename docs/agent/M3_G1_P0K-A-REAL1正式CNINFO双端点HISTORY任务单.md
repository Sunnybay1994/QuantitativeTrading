# M3 G1 P0K-A-REAL1：正式 CNINFO 双端点 HISTORY 任务单

状态：**已执行并通过（raw-first 闭包）；后续 candidate 质量失败转入 P0K-B**

日期：2026-07-30（Asia/Shanghai）

执行角色：主 Agent（用户明确要求本轮省略外部实现与外部初验）

## 1. 目标

在已完成的正式 G1 INDEX、Tushare HISTORY 和 CNINFO rights 闭包上，按 P0K-A 冻结顺序新增：

1. 637 个 `stock_dividend` identity；
2. 637 个 `stock_share_change` identity。

本任务只形成两类官方 JSON raw、metadata、intent、candidate、receipt 和 journal 闭包。
不在本任务实现 P0K-B，不选择新公司行动，不改变 ledger/reconciliation，不运行 REFERENCE、
PREPARE 或 PUBLISH。

## 2. 冻结基线

- 代码 HEAD：`7fa3632`；
- P0K-A 实现提交：`99889ca`；
- Windows 原生解释器：`D:\Miniforge3\python.exe`；
- 正式项目根：当前 Windows 工作区；
- 只读正式 status：exit 0，486.7 秒；
- `completed_stages=["INDEX"]`、`outcome="INCOMPLETE"`；
- `history_requests=3190`、`history_symbols=637`；
- `cninfo_dividend` / `cninfo_share_change` journal 文件数均为 0；
- `data/raw/cninfo/stock_dividend` / `stock_share_change` 文件数均为 0；
- 当前无 `run_g1` writer；
- 配置保持 `request_rate_per_minute=60`、`max_attempts=5`、
  `retry_base_seconds=2.0`，不临时提速。

Windows 原生执行只关闭本任务的正式数据采集，不等于 Linux Gate。

## 3. 执行顺序

### REAL1-A：dividend

唯一网络命令：

```powershell
D:\Miniforge3\python.exe -m quant.research.m3.run_g1 `
  --config configs/research/m3_qlib_example.toml `
  history --max-new-requests 637
```

通过条件：

- 本轮 `new_requests_committed=637`；
- workflow 仍为 INDEX-only / INCOMPLETE；
- 637 个 dividend receipt 与 1,274 个对应 raw/metadata 文件通过生产 verifier；
- share-change connector 未调用，share-change journal/raw 仍为零；
- 无 partial request、孤儿 raw 或重复 request id。

### REAL1-B：share-change

仅在 REAL1-A 通过后执行相同 CLI，预算仍为 637。

通过条件：

- 本轮新增 637 个 share-change receipt；
- 两类 batch 各自与 plan 的 637 个 request id 精确闭包；
- `SECCODE` scope、columns、count/total、raw/metadata/receipt digest 全部通过；
- 若随后的 candidate 审计暴露 600733/P0K-B 业务失败，保留该首败并停止，不将其当作 raw-first
  失败，也不在本任务修改业务选择规则。

## 4. 失败与恢复

- 任一网络、schema、journal、raw 或摘要错误立即停止当前段，不启动后一段；
- 只允许生产 workflow 从完整 evidence 恢复，不删除、不覆盖、不手工补 receipt；
- 预算耗尽导致 INCOMPLETE 是合法结果；
- 进程中断后先确认 writer 消失，再运行零网络 status/生产 verifier；
- API 实际调用数按生产重试合同最多为本段 identity 数的 5 倍；报告只记录可证明的 committed
  数和上限，不猜测 provider attempts；
- 输出不得包含 Enckey、token、响应正文、绝对个人路径或其他凭据。

## 5. 验收记录

每段完成后记录：

- 命令退出码、耗时、CLI 单行 JSON；
- journal receipt 数与 raw/metadata 数；
- request-id 集合闭包和 endpoint 分隔；
- production verifier 结果；
- partial/orphan 数；
- writer 清理状态；
- 首个失败（若有）的 code、operation 与可复现边界。

完成 REAL1-B 后新增主 Agent 验收报告，再进入 P0K-B。

## 6. 执行结论

- REAL1-A：exit 0，2229.1 秒，`new_requests_committed=637`，
  `outcome=INCOMPLETE`，仅 dividend 新增 637 个完整 identity；
- REAL1-B：网络阶段新增 share-change 637 个完整 identity；命令在随后 candidate 审计以
  exit 6、`G1_WORKFLOW_QUALITY_FAILED/HISTORY` 结束，5790.7 秒；
- 两端点 journal 均为 637 个 intent/candidate/receipt，raw 均为 637 个 data +
  637 个 metadata，partial/temp 均为 0；
- 失败发生在所有新响应通过生产 verifier 之后，不属于 raw、metadata、journal、网络或预算失败；
- 按本任务冻结边界停止于 HISTORY，不启动 REFERENCE/PREPARE/PUBLISH。

完整证据见
[`M3_G1_P0K-A-REAL1正式CNINFO双端点HISTORY主Agent最终验收报告.md`](M3_G1_P0K-A-REAL1正式CNINFO双端点HISTORY主Agent最终验收报告.md)。
