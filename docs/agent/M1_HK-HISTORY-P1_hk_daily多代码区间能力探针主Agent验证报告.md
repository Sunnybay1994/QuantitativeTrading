# M1 HK-HISTORY-P1 `hk_daily` 多代码区间能力探针主 Agent 验证报告

日期：2026-07-18  
结论：**当前服务端实测两代码区间完整成功；可进入可恢复批次设计，但未文档化语法必须 fail closed**

## 1. 调用边界

P0 raw 的 `fetched_at` 为 `2026-07-18T20:25:21.406613+08:00`。P1 于
`2026-07-18T21:25:42+08:00` 后发出，满足至少 60 分钟冷却；只调用一次：

```text
hk_daily(
  ts_code="00005.HK,00700.HK",
  start_date="20260414",
  end_date="20260710",
  fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
)
```

没有重试、分页、单代码降级或追加 API 请求；没有写 clean。

## 2. 不可变 raw 回执

| 项目 | 结果 |
|---|---|
| snapshot id | `132620.624930Z-77c02bc1c1a8` |
| raw parquet | `data/raw/tushare/hk_daily_multi_symbol_probe/date=2026-07-18/132620.624930Z-77c02bc1c1a8.parquet` |
| metadata | 同目录 `132620.624930Z-77c02bc1c1a8.json` |
| raw SHA-256 | `6640cb1bb40bdfdd6b6d008e4e8e6f6af76b6a2d0517408c35c42610eeba6cd6` |
| raw 行数 | 120 |

文件 SHA、metadata `checksum_sha256` 和 metadata 行数逐项一致，metadata 不含 token。

## 3. 离线完整性审计

- `00005.HK`、`00700.HK` 各 60 行；证券集合精确，无目标外证券。
- 每只证券的日期集合都与 clean HK 日历最后 60 个开市日
  `2026-04-14..2026-07-10` 完全一致。
- `(ts_code, trade_date)` 重复 0，空值单元格 0，响应 120 行远低于 5000 行上限。
- 经过 HK-only OHLC mapper 后 120 行全部通过 `Bar1dSchema`；本探针没有开盘价越出 high/low 的行。

## 4. 生产边界与后续

Tushare 官方 `hk_daily` 文档明确单次最多 5000 行、支持单代码区间和单日全市场，但没有明确写出港股接口
支持逗号分隔多代码；A 股 `daily` 文档则明确写明该语法。因此本报告只冻结“当前服务端实测成功”，不把
它冒充官方长期保证。

下一步可按 `floor(5000 / 60) = 83` 冻结保守批上限并实现 raw-first、可恢复、逐批精确覆盖验证的 manifest。
任何批次出现额外证券、重复键、目标全缺、精确日期缺口、5000 行截断或供应商拒绝多代码，都必须停止发布
并保留 raw/失败事实；不得在同一运行中静默改成额外 API 请求。`02983.HK` 继续单独处理。
