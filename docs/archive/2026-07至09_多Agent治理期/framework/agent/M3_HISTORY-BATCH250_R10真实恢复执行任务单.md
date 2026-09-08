# M3 HISTORY-BATCH250 R10 真实恢复执行任务单

## 冻结集合

- 前置：verified `1580`、missing `1606`、partial `0`
- 数量上限：`250`
- ordered request-id SHA-256：`395b09e52df262a0ab5c2b73052c5ddc22d55395c85a0cb5bc77f52f55d7f511`
- endpoint：`adj_factor=47`、`daily=44`、`dividend=60`、`stk_limit=46`、`suspend_d=53`
- 首个：`83801695226c1b6b21fa7487bb703992d1ba0258504f9c41601562fc6a930346`（`dividend/600516.SH`）
- 末个：`9757488994b8e5717a043ef0047c34d9271b3d23343a596ad187f77d2db9d49e`（`dividend/600895.SH`）

## 唯一命令与约束

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

- 单写者串行；保持 `60/min`、`max_attempts=5`，不输出 token。
- 项目错误立即停；承载层异常先确认 WSL 子进程/写锁静默。
- 成功条件：新增 `250`、verified `1830`、missing `1356`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

