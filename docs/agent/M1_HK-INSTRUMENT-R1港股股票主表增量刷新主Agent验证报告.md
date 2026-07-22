# M1 HK-INSTRUMENT-R1 港股股票主表增量刷新主 Agent 验证报告

日期：2026-07-18  
结论：R1 通过；HK60 available-history Gate 仍未通过

## 1. 执行与不可变证据

在 WSL Miniforge `base` 中仅执行一次：

```bash
python -m quant.data.update_instruments --source tushare --market HK
```

结果：

- snapshot id：`114420.214870Z-efa1ac848046`
- raw：`data/raw/tushare/instrument/date=2026-07-18/114420.214870Z-efa1ac848046.parquet`
- raw 行数：3539；metadata 行数：3539
- raw SHA-256：`b8a9fe81d33138b09329f599c03e97c1b4930669797cd3114b1d0d8aa8eaff2b`
- metadata 所载 SHA-256 与文件实算值一致
- clean HK Instrument：3250 行，通过 `InstrumentSchema`
- clean SHA-256：`662b9e43006512abf664956fda3dbfabd0fac92d46d9320dc32f89f05b11c368`

## 2. 覆盖结果

SSE 2026-07-10 官方快照证明的 5 个股票型缺口中，以下 4 个已由最新 `hk_basic` 补齐：

| symbol | list_date | board_lot |
|---|---:|---:|
| `00537.HK` | 2026-07-09 | 100 |
| `01377.HK` | 2026-07-09 | 100 |
| `06067.HK` | 2026-06-23 | 500 |
| `06745.HK` | 2026-07-10 | 1000 |

`02983.HK` 未出现在 `hk_basic`。HKEX 官方新上市证券记录将其描述为与 `02525` 相关、因
“Share Subdivision”于 2026-07-10 启用、每手 160 股的临时并行交易柜台。因此本任务没有把它
伪装为普通股票，也没有用港股通资格事件的 `effective_date` 冒充 `list_date`。

## 3. Gate 结论与剩余边界

刷新后，双 Route 真实 available-history Gate 仍返回：

```text
BAR_WINDOW_REFERENCE_INVALID
```

剩余缺口为严格 32 个：31 个 SSE 分类为 ETF 的代码，以及 `02983.HK`。这符合 R1 任务边界；
R1 只刷新 Tushare 普通股票主表，不允许把 ETF 映射为 STOCK。

下一步必须从 HKEX 权威来源补齐 31 个 ETF 的 `list_date`、`board_lot`、名称和币种，并单独处理
`02983.HK` 的临时柜台身份及生命周期。补齐引用后仍需重新运行精确日期 Gate；届时若历史日线仅有
当前少量日期，应返回 `BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE`，不能误报通过。

## 4. 风险

- `02983.HK` 的终止/合并日期需要以公司行动公告为准，不能用当前抓取日推断。
- HKEX ETP 响应包含同代码多日期记录，映射必须按冻结 `as_of` 选不晚于该日的最新记录并拒绝冲突。
- 本报告不宣布 HK60 历史行情 Gate 或 M1 里程碑通过。
