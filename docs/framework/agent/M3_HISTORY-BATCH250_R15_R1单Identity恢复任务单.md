# M3 HISTORY-BATCH250 R15 R1 单 Identity 恢复任务单

## 唯一对象

- request id：`e77989adb2e3210da57ad6728a6cdb862ee1cb4ae928f977cb286ad4c54ec74f`
- endpoint/symbol/window：`suspend_d/300251.SZ/20151009..20260710`
- 恢复前 journal 仅 `intent.json`，raw `ABSENT`。

## 唯一命令

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 1
```

## 通过条件

- 新增 `1`、verified `2859`、missing `327`、partial `0`。
- 单写者，保持既定速率/重试；失败后停止，不第二次重跑。
- 工作流仍为 `[INDEX]/INCOMPLETE`。

