# M3 HISTORY-BATCH100 真实恢复执行与主 Agent 验证报告

日期：2026-07-18  
任务单：[`M3_HISTORY-BATCH100真实恢复执行任务单.md`](M3_HISTORY-BATCH100真实恢复执行任务单.md)  
状态：**通过**；HISTORY/G1/M3 Gate 仍未完成

## 执行边界

- 用户已持续授权 Tushare API，由主 Agent 按 2000 积分权限及端点限频自行统筹。
- 唯一网络命令只执行一次：

```text
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 100
```

- exit 0，约 243.3 秒；`new_requests_committed=100`、`completed_stages=[INDEX]`、`outcome=INCOMPLETE`、无错误码。
- 未并发第二个 writer，未修改 request rate/policy，未启动其他阶段。实际 attempts 无独立证据，只能证明单命令与最多 500 attempts 的合同上限。
- 按用户 24 小时临时流程简化，由主 Agent 直接执行和验证；未调用外部 Agent，不声称外部独立初验。

## 生产验证

零网络 `run_g1 status` exit 0，仍为 `[INDEX]/INCOMPLETE`。随后对全部现有 HISTORY receipt 调用生产 `verify_tushare_receipt`，并用 `RawStore.inspect_request_state()` 检查无 receipt identity：

| 指标 | 执行前 | 执行后 | 增量 |
|---|---:|---:|---:|
| total | 3186 | 3186 | 0 |
| verified reusable | 149 | 249 | +100 |
| missing | 3037 | 2937 | -100 |
| planned partial | 0 | 0 | 0 |

计数守恒与 CLI committed 精确一致。verified endpoint 总计：

```text
adj_factor=48, daily=50, dividend=54, stk_limit=58, suspend_d=39
```

相对前批增量正好为任务书冻结的 `18/11/29/28/14`。计划外目录仍为 132 complete + 1 partial；扣除 127 个 INDEX 后，旧月窗保持 5 complete + 1 partial。

## 下一步

下一批 250 个 missing identity 已零网络冻结：

```text
identity set sha256 = 8347baeeab3f0bc59b394bfe328142031306bd4a7bcbcd8a1930ca4050394792
adj_factor=47, daily=51, dividend=48, stk_limit=45, suspend_d=59
```

HISTORY 尚缺 2,937，仍不得声明 HISTORY/G1/M3 完成。
