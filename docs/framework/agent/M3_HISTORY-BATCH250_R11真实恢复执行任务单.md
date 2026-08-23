# M3 HISTORY-BATCH250 R11 真实恢复执行任务单

## 冻结集合

- 前置：verified `1830`、missing `1356`、partial `0`
- 数量上限：`250`
- ordered request-id SHA-256：`f883d8976d5248e14aab1068dd4a28bbf93c3d3ffadc9e84a65d91b29a097437`
- endpoint：`adj_factor=52`、`daily=49`、`dividend=52`、`stk_limit=52`、`suspend_d=45`
- 首个：`976983ccf4e5d61436b92c6b02e84e4e6d2c050f90388e437a4667955a2ccfa6`（`dividend/600074.SH`）
- 末个：`ab8a9684ac57a6ab7db18e6777b1490e5a7a57081f5be26283f4e5080d70ad1e`（`adj_factor/002608.SZ`）

## 唯一命令与约束

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

- 单写者串行；保持 `60/min`、`max_attempts=5`，不输出 token。
- 项目错误立即停；承载层异常先确认 WSL 子进程/写锁静默。
- 成功条件：新增 `250`、verified `2080`、missing `1106`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

