# M3 HISTORY-BATCH50 R3 R1 单 Identity 恢复任务单

## 目标

仅恢复 BATCH50 R3 留下的唯一 intent-only identity：

- request id：`3930f7579318ce43a6b9f22853ef28bba3dcc452b4f75f35750a164bae91420d`
- endpoint：`stk_limit`
- symbol/window：`688506.SH/20151009..20260710`
- 恢复前 journal 仅有 `intent.json`，raw `ABSENT`。

## 唯一命令

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 1
```

## 约束与通过条件

- 单写者，保持 `60/min`、`max_attempts=5`，不输出 token。
- 承载层断开时先确认 WSL 子进程/写锁静默，绝不并发下发恢复。
- 成功后 verified `677`、missing `2509`、partial `0`；仍为 `[INDEX]/INCOMPLETE`。
- 非零退出且写者静默后只做审计，不第二次重跑。

