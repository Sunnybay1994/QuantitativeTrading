# M3 HISTORY-BATCH25 R5 真实恢复执行任务单

## 冻结集合

- 前置：verified `702`、missing `2484`、partial `0`
- 数量：`25`
- ordered request-id SHA-256：`85def643dad6127ddbf8dec3b91bf5bcf273155727a9c61d0de2853fa836f621`
- endpoint：`adj_factor=7`、`daily=4`、`dividend=6`、`stk_limit=8`、`suspend_d=0`
- 首个：`3b8e23ec902b052ae47f483be79c4db52ff990a6b0a150ee14e480e2654dfbb5`（`stk_limit/603000.SH`）
- 末个：`3e1a5c9f9ec186179bacb67065a68dacdb08528a3c99bd050bb3a07650bdfd5a`（`adj_factor/000961.SZ`）

## 唯一命令与约束

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 25
```

- 单写者，保持 `60/min`、`max_attempts=5`；不输出 token。
- 承载层异常先确认 WSL 子进程/写锁静默；项目失败后不补跑余额。
- 成功条件：新增 `25`、verified `727`、missing `2459`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

