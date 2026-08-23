# M3 HISTORY-BATCH250 R13 真实恢复执行任务单

## 冻结集合

- 前置：verified `2330`、missing `856`、partial `0`
- 数量上限：`250`
- ordered request-id SHA-256：`16d7825623faed08f8776e2bf57f712b3971e1a23727cab4f96542d4996550f0`
- endpoint：`adj_factor=45`、`daily=44`、`dividend=61`、`stk_limit=53`、`suspend_d=47`
- 首个：`bf100f1628980da8bb768612656f03c9c6e87993479c3937b1c269be3e479371`（`suspend_d/600688.SH`）
- 末个：`d11c42cd506566f95e34cdde6e438644fb57be20d5260039e420c4299aff069b`（`suspend_d/600519.SH`）

## 唯一命令与约束

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

- 单写者串行；保持 `60/min`、`max_attempts=5`，不输出 token。
- 项目错误立即停；承载层异常先确认 WSL 子进程/写锁静默。
- 成功条件：新增 `250`、verified `2580`、missing `606`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

