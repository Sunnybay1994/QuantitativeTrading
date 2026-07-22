# M1 HK-HISTORY-P0 `hk_daily` 单次权限与响应探针主 Agent 验证报告

日期：2026-07-18  
结论：**权限通过；覆盖与 Schema 契约未通过，禁止发布 clean**

## 1. 执行边界

按任务单只执行一次 `hk_daily(trade_date=20260710)` 全市场请求。目标集合由已验证的
available-history coverage 派生，共 613 个 `STOCK`，集合 SHA-256 为
`98521912ea17f78cf3859e4b28bbcaa18db83cc06dee7d3544358be5b4bbd13f`。31 个 ETF 未进入请求目标。

本探针只写独立 raw 表 `tushare/hk_daily_access_probe`；没有写 clean、质量报告或复权数据，也没有追加
Tushare 请求。

## 2. 不可变回执

| 项目 | 结果 |
|---|---|
| snapshot id | `122521.406613Z-f5b205dcd4e7` |
| raw parquet | `data/raw/tushare/hk_daily_access_probe/date=2026-07-18/122521.406613Z-f5b205dcd4e7.parquet` |
| metadata | `data/raw/tushare/hk_daily_access_probe/date=2026-07-18/122521.406613Z-f5b205dcd4e7.json` |
| raw SHA-256 | `3f9f163a4ec7e672a0eac6d13ab483e5ff8bc789f46126f6c69fc04a0b5615a2` |
| raw 行数 | 612 |
| 响应字段 | `ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount, _request_symbol, _market` |

raw SHA 与 metadata 中的 `checksum_sha256` 一致，metadata 不含 token 或目标完整清单。

## 3. 验证结果

1. **权限**：成功返回数据，证明当前账号可访问 `hk_daily`；2000 积分本身仍不能替代该独立服务的权限
   说明。
2. **目标覆盖**：613 个目标覆盖 612 个，唯一缺失 `02983.HK`。它是已由 HKEX 公告冻结生命周期的临时
   柜台，不能因为供应商缺行而从 Gate 目标中静默删除。
3. **mapper 结构**：映射后无重复 `(symbol, trade_date)`，关键字段无空值。
4. **Schema 反例**：`02609.HK` 在 2026-07-10 的原始值为 `open=3.08, high=3.06, low=2.92,
   close=2.96, vol=6331700, amount=18947638`，违反现行 `Bar1dSchema` 的 OHLC 包含关系。
5. **发布状态**：Schema 校验失败后停止；clean 未变化，HK60 available-history Gate 仍未关闭。

## 4. 系统不变量与后续条件

- 不把供应商权限成功等同于数据 Gate 通过。
- 不静默修正 `02609.HK` 的原始值，也不在缺少权威语义证据时放宽全市场 Schema。
- 不伪造、前向填充或未经契约排除 `02983.HK`。
- `hk_daily` 单次最多 5000 行，且本账号历史证据显示约 1 次/小时；因此在确认数据源能完整覆盖、Schema
  语义和 clean 合并策略前，不启动约 60 个交易日的逐日回补。

下一步为只读核实 HKEX 是否提供可留存的 60 日股票 OHLCV，并对 `02609.HK` 的开盘竞价/日内高点语义做
权威交叉核验。只有目标覆盖、失败语义和 source 合并契约冻结后，才可形成 HK-HISTORY-R1 回补任务。
