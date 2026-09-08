# M3 HISTORY-BATCH250 R7 真实恢复执行任务单

## 冻结集合

- 前置：verified `977`、missing `2209`、partial `0`
- 数量上限：`250`
- ordered request-id SHA-256：`2ca516f5dcb2f0d9f015231b34fdadcb771f850c7baac09ba37db4811b90461e`
- endpoint：`adj_factor=53`、`daily=58`、`dividend=41`、`stk_limit=49`、`suspend_d=49`
- 首个：`5171ebe54d4dd7fa96ac013b716ae40c1b148ec22bbf18350ca7bd1b212a43b9`（`daily/600566.SH`）
- 末个：`64eee92a2f4f54ecdcfa7e2d516e09405e94cd360d3a610a750dd678237d85c1`（`adj_factor/000656.SZ`）

## 唯一命令与约束

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

- 单写者逐请求串行；保持 `60/min`、`max_attempts=5`，不输出 token。
- 任一项目错误立即停；承载层异常先确认 WSL 子进程/写锁静默，存活时只等待。
- 成功条件：新增 `250`、verified `1227`、missing `1959`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

