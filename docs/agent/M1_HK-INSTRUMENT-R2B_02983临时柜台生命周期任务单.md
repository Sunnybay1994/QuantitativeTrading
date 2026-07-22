# M1 HK-INSTRUMENT-R2B 02983 临时柜台生命周期任务单

日期：2026-07-18  
执行者：主 Agent（24 小时简化流程；不调用外部 Agent）  
状态：已完成（2026-07-18；Instrument 引用闭合，Gate 已进入历史覆盖判定）

## 1. 目标与权威事实

将 `02983.HK` 作为有明确生命周期的临时 `STOCK` 柜台纳入 Instrument，而不是普通新上市公司、ETF
或 `02525.HK` 的别名。

冻结事实：

- 名称：`HESAI-W`
- 关联主柜台：`02525.HK`
- 事件：`SHARE_SUBDIVISION_TEMP_COUNTER`
- `list_date=2026-07-10`
- `delist_date=2026-08-13`（最后交易日，含当日）
- `board_lot=160`
- `currency=HKD`、`instrument_type=STOCK`

HKEXnews 2026-07-10 最终生效公告确认拆股已生效，临时柜台从 7 月 10 日 09:00 交易至 8 月 13 日
16:10；HKSCC `PT/NIS/CCASS/209/2026` 明确临时代码 2983、160 股一手及并行交易结束日。
8 月 17 日旧证书截止与 8 月 24 日 CCASS 转换截止不是最后交易日，禁止冒充 `delist_date`。

## 2. 冻结设计

- 新增版本化 `configs/instruments/hk_temporary_counters_2026.toml`，每条生命周期主键为
  `(symbol, list_date)`，保存关联代码、事件、字段和至少两份官方证据的 URL、公告编号、角色、发布日期、
  SHA-256。
- loader 严格校验版本、市场/来源、字段集合、日期、64 位小写 SHA、目标代码、正整数 board lot、
  必需证据角色，以及同一 symbol 生命周期不重叠。
- as-of 投影选择 `list_date <= as_of` 的最新生命周期；处于闭区间 `[list_date, delist_date]` 时输出
  `LISTED`，晚于 `delist_date` 输出 `DELISTED`，早于首次生命周期稳定失败。
- 投影原始配置事实先经 `RawStore` 写入 `hkex/instrument_temporary_counter_notice`，metadata 绑定 as-of、
  targets、配置版本与 `temporary_counter_lifecycle_as_of_v1`；再通过 `InstrumentSchema` 和
  `CleanInstrumentStore`。
- CLI 新增 `--source hkex-notice --notice-config ...`；仅允许 HK、必须带 as-of/targets/config。其他 source
  携带 `--notice-config` 必须在构造 connector/写盘前失败。
- 当前发布顺序必须位于 Tushare HK 股票刷新之后。由于 Instrument 当前是 symbol 时点投影而非永久身份表，
  后续如需任意 PIT 身份查询，应消费本生命周期事实而非把 `symbol` 当永久身份。

## 3. 失败语义

- `HK_TEMPORARY_NOTICE_INVALID`
- `HK_TEMPORARY_TARGETS_INVALID`
- `HK_TEMPORARY_COVERAGE_INCOMPLETE`
- `HK_TEMPORARY_LIFECYCLE_CONFLICT`

失败时不得写 clean；loader/projection 失败前不得修改原 clean。mapper/Schema 失败时 raw 可保留作为证据。

## 4. 反例与验收

必须覆盖：

- 2026-07-10 与 2026-08-13 均为 LISTED；2026-08-14 为 DELISTED；
- 2026-07-09 无有效投影；
- 将 8 月 17/24 写为 delist、缺最终生效/交易安排角色、哈希非法均拒绝；
- 同一 symbol 生命周期重叠拒绝，2025/2026 不重叠复用可按日期选择；
- `02525.HK` 不得替代 `02983.HK`；board lot 必须保持 160；
- raw metadata 含生命周期选择规则和证据哈希但不含凭据；
- upsert 不覆盖现有 31 个 ETF 和股票；
- 双 Route真实 Gate 在引用闭合后应进入 exact-date coverage 判定，不能继续是 reference invalid。

完整证据见
[`M1_HK-INSTRUMENT-R2B_02983临时柜台生命周期主Agent验证报告.md`](M1_HK-INSTRUMENT-R2B_02983临时柜台生命周期主Agent验证报告.md)。
