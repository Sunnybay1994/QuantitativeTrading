# M3 HISTORY-BATCH250 R12 真实恢复执行任务单

## 冻结集合

- 前置：verified `2080`、missing `1106`、partial `0`
- 数量上限：`250`
- ordered request-id SHA-256：`8a9440aa6ad776d7e415ac4d0dd0801bd9bb822301df0a13bde69445fa53af06`
- endpoint：`adj_factor=55`、`daily=42`、`dividend=58`、`stk_limit=45`、`suspend_d=50`
- 首个：`ab958e99ee6ac870ed5264fc6702090c4959ce840a2f253103af51a5bceb45d9`（`suspend_d/600074.SH`）
- 末个：`bf0244aecfee691511b8639b646caec10f14d51ece778bee1119e265fc7c3f3e`（`adj_factor/601933.SH`）

## 唯一命令与约束

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

- 单写者串行；保持 `60/min`、`max_attempts=5`，不输出 token。
- 项目错误立即停；承载层异常先确认 WSL 子进程/写锁静默。
- 成功条件：新增 `250`、verified `2330`、missing `856`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

