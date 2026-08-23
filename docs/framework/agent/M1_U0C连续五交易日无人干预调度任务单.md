# M1-U0C 连续五交易日无人干预调度任务单

状态：2026-07-18 已实现并预注册；独立初验返工已通过主验，真实 Gate 0/5，最早 2026-07-24 21:30 后判定

## 1. 目标与真实范围

用预配置 Windows Task Scheduler 在五个连续共同开市日唤起 WSL Miniforge base，自动完成 M1 日更及同规范
零网络重放；保留五份 verified receipt、五份脱敏 scheduler log 和 Windows Task history。

冻结 plan：

- sessions：2026-07-20、21、22、23、24（clean SH/SZ/HK 日历均开市且非半日）；
- source：`tushare`；
- symbols：`000001.SZ 600000.SH 00005.HK 00700.HK`；
- `use_adjustment_factors=false`：当前 HK factor 无权限；本 Gate 只验不复权日常运营，不替代港股复权 Gate；
- 每日 21:30 Asia/Shanghai；预期首次运行只调用 A `daily` 一次及 HK `hk_daily` 一次，随后重放零 API；
- 预期 5 个 receipt、20 个目标 bar 逻辑键。

## 2. 调度与运行合同

- Windows Task Scheduler 只负责唤起 WSL Ubuntu；项目命令固定在
  `/home/mabw/AI_Coding_win/QuantitativeTrading` 的 WSL Miniforge `base`，禁止 Windows Python。
- 五个一次性任务分别硬编码 session date；设置 wake、missed start ASAP、`IgnoreNew`、无自动 restart。
- wrapper 调 `quant.data.run_daily` 两次：第一次必须 `SUCCESS`，第二次必须 `ALREADY_COMPLETE` 且
  run_id/receipt selector 相同；否则稳定失败。
- 每日一个 exclusive log；只允许 schema/date/UTC start/end/status/run_id/relative receipt/exit code，禁止 token、
  env dump、绝对路径、底层异常或 `set -x`。
- runner 的 `data/run_state/m1_daily/.writer.lock` 是 WSL 单写者边界；Gate 窗口禁止直接 `quant.data.update`、
  HK finalize 或 Windows/WSL 其他 writer 并发写同一 data root。

## 3. 失败与计数语义

- `ALREADY_COMPLETE` 只允许作为同一 scheduler invocation 的第二次零网络重放；首次即 ALREADY 不计当天成功。
- 任一 FAILED、timeout、人工修复/重跑、writer-active、receipt/clean drift 均使当前五日 streak 失败；不得自动
  retry，须重新冻结后续五个连续共同 session。
- `M1_DAILY_UPDATE_FAILED`/intent-only 可能已消耗 API，先检查进程/锁/receipt/raw，禁止盲目重跑。
- 执行前日历若修订为闭市，现有 runner 必须在 connector 前失败；不得静默 SKIP 或计数。
- timeout/承载层中断不证明 WSL 子进程已结束；先查进程和 writer lock。

## 4. 白名单与非目标

可写：

- `src/quant/data/scheduled_daily.py`
- `src/quant/data/run_scheduled_daily.py`
- `src/quant/data/audit_daily_streak.py`
- `scripts/run_m1_daily_streak.sh`
- 对应 unit tests、任务/预验收报告、scheduler XML/hash 产物与必要状态文档

现有 `daily_run.py`、`run_daily.py`、pipeline/storage/connector 均只读。非目标：长期 recurring scheduler、自动
节假日 SKIP、自动 retry、大范围证券覆盖、复权收益 Gate。

## 5. 验收

现在可关闭：wrapper 的双状态/同 identity 校验、脱敏失败、exclusive log、审计器 5 日期/receipt/log 闭包、
Windows/WSL 离线测试、五个 Task 定义预注册与 XML/hash。

必须等待：五次 scheduler 首次 `SUCCESS`、五次自动 `ALREADY_COMPLETE`、五套真实 raw/quality/clean/receipt、
Task history 和最终 streak audit PASS。任何 fake clock/fixture 不能关闭真实五日 Gate。
