# M3 HISTORY-BATCH100 R2 R1 单 Identity 恢复任务单

> **事后纠正：本任务不应下发。** 下发前原 BATCH100 WSL 子进程仍存活，下面识别的 intent-only 只是
> 活动写者的中间状态。该命令实际在原写者释放锁后提交了下一个缺失 identity，而非恢复该中间状态。

## 目标与唯一对象

恢复外层超时留下的唯一合法 intent-only identity，不补跑原批次余额。

- request id：`37d6f4c9315c926a937f58e7c4a9e0377702ffb3896f1887495a90da8b915609`
- endpoint：`daily`
- 恢复前：journal 仅有 `intent.json`，raw `ABSENT`，无 receipt。

## 唯一执行命令

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 1
```

## 约束与通过条件

- 命令只执行一次；命令承载层 timeout 必须覆盖真实网络重试窗口。
- 保持单写者、`60/min`、`max_attempts=5`；不提高速率、不输出 token。
- 非零退出后停止，不执行第二次恢复。
- 成功后零网络全量验证必须为：history `3186`、verified `658`、missing `2528`、partial `0`。
- 不构建候选、不 prepare、不 publish；预期仍为 `[INDEX]/INCOMPLETE`。

## 实际结果

- 原 BATCH100 后台进程完整提交其冻结的 100 个 identity，总 verified 达到 `673`。
- 本命令随后提交 index `673` 的下一 identity：
  `38e32d40b0c6f26d1e27845caa7e7570388eda97e782694192fd921347960e8b`
  （`daily/002466.SZ/20151009..20260710`）。
- 静默态全量生产验证：verified `674`、missing `2512`、partial `0`。
- 该额外请求仍属于确定性 HISTORY plan 和用户授权的 API 范围，但不是本任务冻结的唯一恢复对象；因此本任务按流程判断为**未按目标执行**，不能标记通过。

