# M3 HISTORY-BATCH250 R6 真实恢复执行任务单

## 目标与冻结集合

从 verified `727`、missing `2459`、partial `0` 的静默账本，串行处理确定性 plan 的下一前缀，最多 `250` 个 identity。

- ordered request-id SHA-256：`80b69ca2f45d31d60ba6f0a3582ad19a43fadd4053bc85b97f94ed16ed17143b`
- endpoint：`adj_factor=52`、`daily=61`、`dividend=46`、`stk_limit=48`、`suspend_d=43`
- 首个：`3e254bc5c722a83b63b46faff2e9a31ab413f73eec472fce134b3d02c027e1c0`（`suspend_d/002812.SZ`）
- 末个：`515e894033b61f7b9212b215e95987fdd76168a2e16b072e859a4559485316f4`（`daily/688072.SH`）

## 唯一命令

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

## 风险控制与通过条件

- 仍是一个写者、逐 request 串行，不增加并发；保持 `60/min`、`max_attempts=5`，不输出 token。
- `250` 只是成功时的上限。任一请求失败，生产工作流立即停在该 identity，不跳过、不补跑余额。
- 承载层异常先确认 WSL 子进程/写锁静默；原写者存活时只等待。
- 成功条件：新增 `250`、verified `977`、missing `2209`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。
- 失败条件：静默后精确记录合法提交前缀和至多一个 partial，再另行冻结单 identity 恢复。

