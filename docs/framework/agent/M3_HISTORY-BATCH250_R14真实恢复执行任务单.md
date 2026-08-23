# M3 HISTORY-BATCH250 R14 真实恢复执行任务单

## 冻结集合

- 前置：verified `2580`、missing `606`、partial `0`
- 数量上限：`250`
- ordered request-id SHA-256：`914b988b4fe8d110075faee3d354d60a15ebfb021554d988e70f3eb4d35c38c6`
- endpoint：`adj_factor=40`、`daily=62`、`dividend=50`、`stk_limit=52`、`suspend_d=46`
- 首个：`d12f76a0a0ebb7afe5dd03e50e43b2eb79e43bd38a66642d5f7c08dc2fe94199`（`daily/600340.SH`）
- 末个：`e4cb510ebddc7ce3ccd6e54df716830252370be923d5dce4b87ff0b7dd9b233b`（`suspend_d/600362.SH`）

## 唯一命令与约束

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

- 单写者串行；保持 `60/min`、`max_attempts=5`，不输出 token。
- 项目错误立即停；承载层异常先确认 WSL 子进程/写锁静默。
- 成功条件：新增 `250`、verified `2830`、missing `356`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

