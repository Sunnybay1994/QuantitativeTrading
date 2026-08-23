# M1-U0B 每日运行单实例与完成收据主 Agent 验证报告

## 结论

通过离线代码合同与 Windows/WSL 双平台定向验收。新入口 `python -m quant.data.run_daily` 为显式单日运行提供：

- 跨进程全局单写者；
- path-independent 严格 `run_id`；
- immutable intent/manifest/receipt；
- raw data/metadata、质量报告与 clean 语义投影闭包验真；
- 已完成规范的零 pipeline/connector 调用 `ALREADY_COMPLETE` replay；
- manifest 已发布但 receipt 未发布时的零网络恢复；
- 脱敏稳定失败码与仅相对 selector 的 CLI 输出。

本轮按用户 2026-07-18 的 24 小时临时授权，由主 Agent 直接设计、实现、审查与验证；暂停外部实现 Agent 和外部独立初验，因此本报告不声称完成外部独立初验。

## 实现摘要

### `src/quant/data/daily_run.py`

- `DailyRunSpecV1` 绑定日期、source、排序去重 symbols、factor 模式及涉及市场目标日的完整 clean calendar 行；绝对路径、PID、主机名和抓取时间不进入身份。
- `build_daily_run_spec()` 在 update callable/pipeline 构造前完成日历精确覆盖与开市检查。
- `execute_daily_run()` 复用已验收 `hold_journal_writer_lock()`，并把底层锁码映射为 M1 稳定错误码。
- `data/run_state/m1_daily/<run_id>/` 下发布 canonical `intent.json`、`manifest.json` 和 `receipt.json`。
- intent/manifest/receipt 使用 file flush/fsync 后 exclusive hardlink no-clobber；POSIX fsync 目录，Windows 明示 directory-fsync no-op，不夸大两平台掉电持久性。
- receipt 绑定 intent、manifest、bar/factor raw data+metadata 与质量报告的相对 selector、size、SHA-256。
- clean 不绑定整个可变 Parquet 文件，而重算目标语义投影：bar 为 `session_date × source × symbols` 精确键；factor 为 `source × symbols × effective_date<=session_date`。后续无关证券或未来 factor 合法新增不使历史收据漂移，相关行变化则返回 `M1_DAILY_CLEAN_DRIFT`。
- 当前 calendar 行漂移、raw/metadata 闭包不一致、quality 未通过、canonical JSON 非法、路径逃逸、symlink/非普通文件/hardlink alias 或任一 artifact 漂移均 fail closed。

### `src/quant/data/run_daily.py`

- 新增显式 `--date/--symbols/--source` 的 operational runner；不暴露跳过日历检查的参数。
- `--without-adjustment-factors` 保持现有显式不复权边界。
- update closure 保持 lazy；已有完整 receipt 时不调用 `build_pipeline()`。
- 成功只输出 `status/run_id/receipt_selector`，失败只输出 `status/code`；不输出 Windows/WSL 绝对路径或底层 cause。

### 测试与文档

- 新增 `tests/unit/test_m1_daily_run.py` 与 `tests/unit/test_m1_daily_cli.py`。
- README 增加 receipt-backed runner、低层 `quant.data.update` 边界及 OS scheduler 非目标说明。
- `BarUpdatePipeline` 公共接口与底层 CLI 保持兼容。

## 对抗性证据

测试覆盖：

- 完成后二跑为 `ALREADY_COMPLETE`，update/connector 零调用；
- manifest-only 崩溃状态零网络发布 receipt；
- symbols 顺序/重复不影响身份，source/factor/calendar 语义改变会改变身份或拒绝 replay；
- 锁竞争稳定返回 `M1_DAILY_WRITER_ACTIVE`；
- intent、manifest、receipt、raw metadata、quality 或相关 clean 行篡改均零网络拒绝；
- canonical 文件的 BOM、CRLF、duplicate key 和 hardlink alias 拒绝；
- Windows 既有 quality JSON 的 CRLF 被 artifact hash 绑定并正常解析，不放宽 M1 canonical 文件；
- bar 分区追加无关证券仍可 replay，目标证券变化报 drift；
- factor 新增目标日后的事件仍可 replay，目标日及以前事件变化报 drift；
- update 异常只保留 intent，不发布伪成功 manifest/receipt，错误文本不泄露；
- 原有 bar pipeline 10 项回归保持通过。

## 验证结果

Windows Miniforge `py312`：

```text
ruff check <U0B code/tests> -> passed
mypy src/quant/data/daily_run.py src/quant/data/run_daily.py -> passed
pytest U0B unit/CLI + bar pipeline -> 30 passed
```

WSL Miniforge `base`（项目权威环境）：

```text
ruff check <U0B code/tests> -> passed
mypy src/quant/data/daily_run.py src/quant/data/run_daily.py -> passed
pytest U0B unit/CLI + bar pipeline -> 30 passed
```

两端各出现 1,451 条既有 Pandera/Polars concat 弃用警告，不影响结论。

## 剩余风险与未关闭 Gate

- U0B 不把 factor clean 与 bar clean 变成物理事务；无 receipt 的部分发布不会被当作完成。manifest 成功发布后可零网络恢复 receipt；manifest 之前崩溃仍需幂等重跑现有 pipeline，可能再次访问数据源。
- Windows 明示不提供 POSIX directory fsync 等价保证；项目业务 Gate 仍以 WSL 为权威，同一数据目录禁止 Windows Python 与 WSL Python 并发写入。
- 本轮未创建 cron/Windows Task Scheduler，也未自动选择“当前应跑交易日”。真实 M1 Gate 仍需未来五个连续自然开市日、预配置调度器历史、五份 verified receipt 以及至少一次完成后安全重触发证据。
- 港股 60 日历史、5 只缺失股票 instrument 权威字段及 31 只 ETF 的显式排除/补源仍是独立未完成项。
