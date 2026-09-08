# M1 SSE-REAL2 双 Route 历史 Universe 发布任务单

## 1. 前置与授权

默认未授权。必须同时满足：

1. SSE-REAL1 已完成，独立验证确认 SH clean 1212 行、ADD=794、REMOVE=418、reverse=268/PASS；
2. 用户明确允许原子替换 `SH_CONNECT` 与 `SZ_CONNECT` 两个 universe membership clean 文件；
3. E5 主验报告仍为当前代码基线。

## 2. 外部执行 Agent

全新 `cursor-grok-4.5-high`。先分别运行两条 `--dry-run`，要求 SH/SZ 均 PASS；记录两个既有 universe 目标的
bytes hash/mtime。然后严格串行：

```bash
python -m quant.data.rebuild_connect_universe \
  --route SH_CONNECT --baseline-date 2014-11-17 \
  --mode reverse-audit --snapshot-date 2026-07-10 \
  --expected-baseline-count 268

python -m quant.data.rebuild_connect_universe \
  --route SZ_CONNECT --baseline-date 2016-12-05 \
  --mode reverse-audit --snapshot-date 2026-07-10 \
  --expected-baseline-count 417
```

SH 失败则不得启动 SZ。禁止网络、代码/配置/raw/event/snapshot/calendar 变更、legacy 读取、手工 Parquet 修复。
唯一执行报告：`docs/framework/agent/M1_SSE-REAL2双Route历史Universe发布执行报告.md`。

## 3. 外部独立验证 Agent

另一全新 `cursor-grok-4.5-high`；所有数据/代码只读，唯一写验证报告。

1. 两路分别重新 dry-run，输出须与发布命令 rows/symbols/open_intervals 精确一致；
2. repository reader + `UniverseMembershipSchema` 验证两个目标，无重复/重叠/倒置区间；
3. SH `coverage_start=2014-11-17`、current open=644；SZ `coverage_start=2016-12-05`、rows=1149、
   symbols=1014、open=644；SH rows/symbols 以执行 dry-run 冻结值为准；
4. `eligible_symbols_on` 在 baseline 日数量分别 268/417，在 2026-07-10 分别 644/644；早于 baseline 一日
   均 fail-closed；
5. universe 之外的 raw/clean bytes hash 不变；无 temp 残留；
6. 不联网、不修复、不运行 pytest。

唯一验证报告：`docs/framework/agent/M1_SSE-REAL2双Route历史Universe发布独立验证报告.md`。验证通过后交主 Agent 终验，
再决定是否勾选路线图 M1 历史状态机项。
