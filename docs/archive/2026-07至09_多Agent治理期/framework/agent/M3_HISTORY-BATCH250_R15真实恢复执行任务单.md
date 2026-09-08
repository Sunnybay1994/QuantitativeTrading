# M3 HISTORY-BATCH250 R15 真实恢复执行任务单

## 冻结集合

- 前置：verified `2830`、missing `356`、partial `0`
- 数量上限：`250`
- ordered request-id SHA-256：`b05f0e065db745e35982832e148c4cd7953523fbd3c92e6001f76521ca353c23`
- endpoint：`adj_factor=46`、`daily=45`、`dividend=48`、`stk_limit=45`、`suspend_d=66`
- 首个：`e4de724719579b49a6eab4848e8cbcd2140b550b87bbbdb961f92739b95c23e0`（`daily/002426.SZ`）
- 末个：`f8479c709d10ff6276bedea07b85d61b49764f899bb3f63a59629c5f42349eb6`（`stk_limit/002465.SZ`）

## 唯一命令与约束

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 250
```

- 单写者串行；保持 `60/min`、`max_attempts=5`，不输出 token。
- 项目错误立即停；承载层异常先确认 WSL 子进程/写锁静默。
- 成功条件：新增 `250`、verified `3080`、missing `106`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。

