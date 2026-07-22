# M3 HISTORY-BATCH250 R16 真实恢复执行任务单

## 冻结集合

- 前置：verified `2859`、missing `327`、partial `0`
- 数量上限：`250`
- ordered request-id SHA-256：`047a27bd98bbab10c7fc1ae48d2301dc696c3572afee4b6f93857d3d5b552744`
- endpoint：`adj_factor=45`、`daily=43`、`dividend=50`、`stk_limit=47`、`suspend_d=65`
- 首个：`e77bdd2cc18ddd8f44a22336b65cd754d1a5a4486fd296808ecb0f20268f7d44`（`suspend_d/000581.SZ`）
- 末个：`fa7b51141aa6d9ca8cbde9ebb651fa4761819bb8f40aafb87a17c1864bea0266`（`stk_limit/601099.SH`）

## 唯一命令与约束

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

- 单写者串行；保持 `60/min`、`max_attempts=5`，不输出 token。
- 项目错误立即停；承载层异常先确认 WSL 子进程/写锁静默。
- 成功条件：新增 `250`、verified `3109`、missing `77`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

