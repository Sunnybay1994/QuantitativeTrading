# M1-U0B 每日运行单实例与完成收据实现任务单

## 1. 目标与流程边界

为现有单日 `BarUpdatePipeline` 增加一个上层运行编排，使同一数据目录只有一个 M1 daily writer，并使已完成的同一严格运行规范能够在零 connector 调用下验真复用。

本轮按用户 2026-07-18 的 24 小时临时授权，由主 Agent 直接设计、实现、审查与验证，暂停外部实现 Agent 和外部独立初验。本任务不创建 Windows Task Scheduler/cron，不执行真实网络请求，也不把 fixture 五日测试表述为真实五交易日 Gate。

## 2. 权威契约

- bar、factor、calendar Schema：`src/quant/domain/schemas.py`。
- raw/clean 存储语义：`src/quant/data/storage.py`。
- bar 门禁与质量报告：`src/quant/data/quality.py`。
- 已验收跨平台单写者原语：`src/quant/data/_journal_lock.py::hold_journal_writer_lock`；本任务不修改锁实现。
- `quant.data` 不反向依赖 `quant.research`。M3 receipt 与 storage 私有 helper 均不直接 import；本包只实现 M1 所需的窄 canonical JSON、语义投影摘要和 exclusive hardlink 发布边界。

## 3. 严格运行身份

新增 `DailyRunSpec`。`run_id` 是下列 canonical JSON 的裸 SHA-256：

- schema/contract version；
- `session_date`；
- `source`；
- 排序去重后的标准证券代码；
- `use_adjustment_factors`；
- 涉及市场在目标日的 clean calendar 完整行身份：`market/date/is_open/is_connect_open/is_half_day`；
- 固定的 data layout 与 quality contract version。

身份禁止包含绝对路径、PID、主机名、抓取时间或 token。目标日必须由所有涉及市场的 clean 日历精确覆盖并确认开市，且此检查发生在 connector/pipeline 构造前。

## 4. Journal 与收据

全局 journal：`data/run_state/m1_daily/`；全局 `.writer.lock` 覆盖完整的“验真或执行—发布”临界区。

单次目录：

```text
data/run_state/m1_daily/<run_id>/
  intent.json
  manifest.json
  receipt.json
```

- `intent.json`：严格规范字节，write-once；既有字节必须完全一致。
- `manifest.json`：成功 pipeline 的 immutable raw 身份、质量报告相对 selector、bar clean 目标日+证券逻辑切片摘要；启用 factor 时另绑定截至目标日的对应证券 factor clean 逻辑切片摘要。
- `receipt.json`：M1 窄收据，以 exclusive hardlink no-clobber 发布，绑定 intent、manifest、raw data/metadata 和质量报告的相对 selector、size 与 SHA-256。发布语义为 file flush/fsync 后 hardlink；POSIX 再 fsync 目录，Windows 明示 directory-fsync no-op，不声称两平台具有相同掉电持久性。

clean Parquet 是可增量更新的共享文件，receipt 不直接绑定整个文件字节；公共 verifier 必须重新读取 Schema 合法的目标逻辑切片并与 manifest 摘要比较。这样后续日期或同分区的其他证券合法新增不会使旧收据漂移，但同证券目标切片被改变时必须 fail closed。

## 5. 执行与失败语义

1. 规范、日历或路径非法：connector 构造前稳定失败。
2. 取得全局 writer lock。
3. 写入或严格复核 intent。
4. receipt 存在：完整重验 intent、receipt、raw、质量报告和 clean 逻辑切片；通过则返回 `ALREADY_COMPLETE`，执行 callable 调用次数为零。
5. receipt 不存在：调用现有 pipeline 一次；pipeline 失败不得发布 manifest/receipt。
6. pipeline 成功后重验其 raw/quality/clean 闭包，write-once 发布 manifest，再发布 receipt，最后再次走公共 verifier，返回 `SUCCESS`。
7. receipt/manifest/raw/quality/clean 缺失、损坏、篡改或字段闭包不一致均 fail closed；不得联网“自动修复”既有完成证据。
8. CLI 只输出脱敏单行 JSON：`status/run_id/receipt_selector`；稳定失败只输出错误码，不输出绝对路径、token 或底层 cause。

## 6. 白名单

- 新增 `src/quant/data/daily_run.py`
- 新增 `src/quant/data/run_daily.py`
- 新增 `tests/unit/test_m1_daily_run.py`
- 新增 `tests/unit/test_m1_daily_cli.py`
- 定向更新 `README.md` 的 M1 调用说明
- 任务/主 Agent 验证报告

除非测试证明必要，不修改 `pipeline.py`、`storage.py`、`quality.py`、`_journal_lock.py` 或 M3 receipt 实现。

## 7. 必须覆盖的反例

- 同一规范连续调用两次：第二次 `ALREADY_COMPLETE`，执行 callable/connector 调用为零。
- symbol 输入顺序和重复不改变规范身份；source、日期、factor 模式或 calendar 行改变时身份改变。
- 休市日、缺日历、重复/非法 calendar 行在 callable 构造前失败。
- 持锁并发调用稳定返回 `JOURNAL_WRITER_ACTIVE`，不执行 callable。
- intent、manifest、receipt、raw、quality 或 clean 目标切片任一篡改：零 callable、fail closed。
- shared clean 文件新增非目标证券不影响旧 receipt；改变目标证券行则拒绝。
- factor 模式关闭时不得要求 factor 产物；开启时 factor raw/clean 闭包缺失必须拒绝。
- CLI 成功和失败输出均不含 Windows/WSL 绝对路径或异常 cause。

## 8. 验收命令

Windows `py312` 与 WSL Miniforge `base` 各执行：

```text
python -m pytest tests/unit/test_m1_daily_run.py tests/unit/test_m1_daily_cli.py -q
ruff check src/quant/data/daily_run.py src/quant/data/run_daily.py tests/unit/test_m1_daily_run.py tests/unit/test_m1_daily_cli.py
mypy src/quant/data/daily_run.py src/quant/data/run_daily.py
```

随后执行受影响的 pipeline 回归：

```text
python -m pytest tests/integration/test_bar_pipeline.py -q
```

## 9. 非目标与剩余 Gate

- 不建立 OS 调度任务，不选择“当前应跑交易日”，本轮 CLI 仍显式传 `--date` 与 `--symbols`。
- 不承诺跨 bar/factor clean store 的物理事务；receipt 只会在完整闭包验真后存在，崩溃产生的无 receipt 状态不得冒充完成。
- receipt 前崩溃后的零网络 raw 重用需要 deterministic request raw 改造，另立任务，不在本包扩张。
- M1 路线图“连续 5 个真实交易日无人干预”仍需未来五个自然开市日、预配置 OS scheduler 历史及五份 verified receipt；本轮不能勾选该 Gate。
