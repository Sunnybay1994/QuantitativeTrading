# M1 HK-INSTRUMENT-R2B 02983 临时柜台生命周期主 Agent 验证报告

日期：2026-07-18  
结论：R2B 通过；HK60 Instrument 引用已闭合，Gate 已进入真实历史覆盖失败

## 1. 权威事实与实现

- HKEXnews 最终生效公告确认拆股于 2026-07-10 生效，临时柜台自当日 09:00 交易至
  2026-08-13 16:10，每手 160 股。
- HKSCC `PT/NIS/CCASS/209/2026` 明确临时代码 2983、并行交易起止及 160 股一手。
- 两份 PDF 实算 SHA-256 已写入版本化
  `configs/instruments/hk_temporary_counters_2026.toml`。8 月 17 日证书截止和 8 月 24 日 CCASS 转换截止
  与最后交易日分字段保存，loader 要求 `delist_date == parallel_trading_end`。
- loader 严格校验字段、角色、哈希、代码、日期和生命周期不重叠；as-of 投影支持临时代码跨年份复用，
  不把 symbol 当永久身份。
- 配置事实先写 `hkex/instrument_temporary_counter_notice` raw，再以
  `temporary_counter_lifecycle_as_of_v1` 投影为 canonical Instrument。

最终发布行：

```text
02983.HK | HESAI-W | STOCK | HKD | 2026-07-10..2026-08-13 | board_lot=160 | LISTED
```

`02525.HK` 仅作为 `related_symbol` 保存在 raw 事实中，没有替代 02983。

## 2. 自动验证

Windows Miniforge 与 WSL Miniforge `base` 的 HKEX Instrument 合流组均为：

```text
31 passed
```

Ruff 通过，WSL 定向 mypy 通过。测试覆盖闭区间端点、8 月 14 日 DELISTED、上市前失败、误用 8 月
17/24 日、缺官方角色、非法哈希、生命周期重叠、非重叠代码复用、raw 证据闭包和现有 ETF 保留。

## 3. 真实发布闭包

- snapshot id：`122017.180956Z-1beb4761c063`
- raw：`data/raw/hkex/instrument_temporary_counter_notice/date=2026-07-18/122017.180956Z-1beb4761c063.parquet`
- raw 行数：1
- raw SHA-256：`3c56d9b044f09bfc6c14430666192a122d933939342733124a279e7e3ecd0daa`
- metadata SHA 与实算一致
- 发布后 HK Instrument：3282 行，通过 `InstrumentSchema`
- clean SHA-256：`1aabba33ad5e777ac1dd84c2a9b7248b6f626e172fce50d947b5639887ebd531`

## 4. Gate 状态转移

双 Route `as_of=2026-07-10`、Tushare、60 观测、`--require-available-history` 均已从：

```text
BAR_WINDOW_REFERENCE_INVALID
```

进入：

```text
BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE
```

紧凑证据（两 Route 当前集合相同）：

- eligible：644
- 合法排除 ETF：31
- required stocks：613
- 结构性短历史股票：11
- 缺历史股票：613
- 缺失 required sessions：36374
- unexpected sessions：0

这证明引用契约已闭合，剩余阻断是实际港股日线历史尚未取得，而不是证券类型/上市期错误。当前 clean 只有
`00005.HK` 与 `00700.HK` 各 1 日，不能宣布 HK60 或 M1 Gate 通过。

## 5. 剩余风险

- Tushare 官方权限表把 `hk_daily` 列为独立付费港股日线服务，不等同于 2000 积分 `hk_basic`；历史回补前
  必须先做单次有界真实权限探针。
- 没有港股逐日停牌事实时，停牌造成的合法无 bar 仍会被 exact-date Gate 视为缺口；不得静默填充。
- 当前 Instrument 是 as-of 投影；未来刷新 Tushare HK 股票后应重放 HKEX notice 覆盖，避免临时柜台权威
  生命周期被供应商普通主表意外改写。
