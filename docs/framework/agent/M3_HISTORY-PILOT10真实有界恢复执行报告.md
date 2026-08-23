# M3 HISTORY-PILOT10 真实有界恢复执行报告

日期：2026-07-18  
执行角色：主 Agent（依据用户 24 小时临时流程简化授权直接执行）  
任务单：[`M3_HISTORY-PILOT10真实有界恢复执行任务单.md`](M3_HISTORY-PILOT10真实有界恢复执行任务单.md)  
状态：**执行成功，待/已由主 Agent 直接验证**；不代表 HISTORY、G1、M3 或后续 Gate 完成

## 1. 执行前条件

- 当前 WSL 逻辑路径：`/home/mabw/AI_Coding_win/QuantitativeTrading`；物理路径：
  `/mnt/f/AI_Coding/QuantitativeTrading`；Windows 映射：`F:\AI_Coding\QuantitativeTrading`。
- `.git` 不是有效仓库；只确认 `.gitignore:27` 存在精确规则
  `configs/tushare.local.toml`。未读取、输出或复制本地配置及 token，不声称 Git runtime ignore 已验证。
- [`XP0_Linux_Windows跨平台JournalLock主Agent最终验收报告.md`](XP0_Linux_Windows跨平台JournalLock主Agent最终验收报告.md)
  已通过，PILOT10 的 writer-lock 前置阻塞解除。
- 公开配置核对：`request_rate_per_minute=60`、`max_attempts=5`、`retry_base_seconds=2.0`。
- 零网络公开 status：exit 0，`completed_stages=[INDEX]`、`history_symbols=637`、
  `history_requests=3186`、`outcome=INCOMPLETE`。
- 逐 receipt 生产 verifier：`verified_reusable=114`、`missing=3072`、计划内无 receipt 的 partial 目录为 0。

冻结的前 10 个缺失 identity 全部属于 `suspend_d`：

```text
00d096993ae4ee2e11ae3a4f017260f4267d881720c5f92d47c9edebe68d36a4
00d5012c85bf34aea483ce333fb45e0648145eca3886085a595a6285c47640f0
00e016543429220940903a099b3818a8aa3501bf1e0762a6970de759e4b67845
0101b7bca2a84d2dcbfa8f479d54f15f76a0430140a2633adac9e4852ab9b78d
0127a3830218fa25876df875ceeb9d46ea35b6afb04f5a2b51c81acea3b1d39e
01ef459dd3f74e8007826bd6d3d5a68585af8432370ba72844141a117b022bd6
02135983a0ad3162793cc697d762fcb416e3e816c18ea956ffdfa8ff2bcf76a1
0384ccdb8917cb908496536a9bdf15731d370406ea01775d57f968ae60b5d9ae
04512ec824a67e120a8300e1dbd359a8643a0ac3a00dedb345d2f2b8e9e24234
0591444fc8b2fb2ec1fe3456826026b2580dc4cbb785f06788948b4624d5cb62
```

identity 集合摘要：`8cf2caf790031ad37c0686118ae7221f1e329a2f8a9ea7b4f235424af87ce01e`。

## 2. 唯一网络命令与结果

只执行了一次任务单允许的命令：

```text
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 10
```

结果：exit 0，约 158.1 秒；CLI：

```json
{
  "command": "history",
  "completed_stages": ["INDEX"],
  "error_code": null,
  "error_operation": null,
  "history_requests": 3186,
  "history_symbols": 637,
  "max_new_requests": 10,
  "new_requests_committed": 10,
  "outcome": "INCOMPLETE"
}
```

未重复命令、未扩大 N、未启动 `reference/prepare/publish/run-all`、未改代码/测试/配置。

API attempt 总数不能从 receipt 或 CLI 结果独立反推；可证明的边界是：只启动一次命令、10 个 committed
identity、冻结配置每 identity 最多 5 attempts，因此合同上限不超过 50 attempts。本报告不把该上限误写为
实际发生了 50 次，也不声称没有内部重试。

## 3. 执行后零网络核验摘要

生产 `verify_tushare_receipt` 对当前计划全部已有 receipt 逐条验证通过：

| 指标 | 执行前 | 执行后 | 增量 |
|---|---:|---:|---:|
| HISTORY plan total | 3186 | 3186 | 0 |
| verified reusable | 114 | 124 | +10 |
| missing | 3072 | 3062 | -10 |
| planned partial without receipt | 0 | 0 | 0 |

执行后 endpoint 分布：

```text
adj_factor=28, daily=36, dividend=21, stk_limit=29, suspend_d=10
```

新增 10 个全部为 `suspend_d`，其 spec/request/raw identity、receipt digest、endpoint policy 与 raw bundle
均由生产 verifier 闭合。旧式无 `ts_code` 月窗 `suspend_d` 仍为 5 个完整 receipt + 1 个仅 intent 的不完整
目录，未计入新计划 reusable，也未被删除或覆盖。

最终零网络 status：exit 0；`completed_stages=[INDEX]`、`history_requests=3186`、
`history_symbols=637`、`outcome=INCOMPLETE`。

## 4. 范围边界

- 本次只证明首批 10 个真实 HISTORY identity 的预算、持久化和验证闭环。
- HISTORY 仍缺 3062 个 identity，`HISTORY` 阶段未完成。
- 未验证真实 API attempt 精确次数；只验证了任务书可证明的上限。
- 未运行下一批、REFERENCE、PREPARE、PUBLISH、G2-G9 或 M3 Gate。

