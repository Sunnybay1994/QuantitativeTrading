# M3 HISTORY-BATCH250 R9 R1 单 Identity 恢复任务单

## 唯一对象

- request id：`837804b49c95606e52f9f99fc81ebc544039dee84de65f02e2fb4c62a2250a1d`
- endpoint/symbol/window：`daily/600426.SH/20151009..20260710`
- 恢复前 journal 仅有 `intent.json`，raw `ABSENT`。

## 唯一命令

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 1
```

## 约束与通过条件

- 单写者；保持 `60/min`、`max_attempts=5`，不输出 token。
- 承载层异常必须先确认 WSL 子进程/写锁静默；不并发恢复。
- 成功后 verified `1580`、missing `1606`、partial `0`，仍为 `[INDEX]/INCOMPLETE`。
- 项目失败后停止，不第二次重跑。

