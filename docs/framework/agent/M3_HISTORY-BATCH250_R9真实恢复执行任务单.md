# M3 HISTORY-BATCH250 R9 真实恢复执行任务单

## 冻结集合

- 前置：verified `1477`、missing `1709`、partial `0`
- 数量上限：`250`
- ordered request-id SHA-256：`90ddebef90ffee3ac1804b0f68a0fbb6ff55081f2816e92e2342060479d4c27e`
- endpoint：`adj_factor=55`、`daily=46`、`dividend=55`、`stk_limit=47`、`suspend_d=47`
- 首个：`7a7de4ed63ce45bac919bcba13c2f706408ecf327f6520fb3bb3ec7c140f80cf`（`daily/601989.SH`）
- 末个：`8fb26b3b5b3a5215e71c726b85da7ba8054b91a97ca097f97da982aaa2365506`（`suspend_d/601166.SH`）

## 唯一命令与约束

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

- 单写者逐请求串行；保持 `60/min`、`max_attempts=5`，不输出 token。
- 项目错误立即停；承载层异常先确认 WSL 子进程/写锁静默。
- 成功条件：新增 `250`、verified `1727`、missing `1459`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

