# Futu OpenD A 股历史分钟实测（2026-09-10）

结论：当前已登录的 OpenD 可以获取沪深个股及沪市 ETF 历史 1 分钟行情。实际保存 82,904 条不复权分钟数据，覆盖两个完整季度样本及 2019 年初小样本。

## 实测结果

| 标的 | 2025 年第一季度 | 2026 年第一季度 |
|---|---:|---:|
| SH.600000 浦发银行 | 13,737 条，57 日 | 13,496 条，56 日 |
| SZ.002027 分众传媒 | 13,737 条，57 日 | 13,496 条，56 日 |
| SH.518880 黄金 ETF | 13,737 条，57 日 | 13,496 条，56 日 |

- 2025 样本实际日期：2025-01-02 至 2025-03-31；2026 样本：2026-01-05 至 2026-03-31。每个标的每季度 14 页，每页上限 1,000 条，均取至无后续分页。
- SH.600000 的 2019-01-02 至 2019-01-08 另外返回 1,205 条、5 日。官方说明分钟 K 线最近 8 年；本轮远端点验到 2019 年初，未穷举所有历史日期。
- 每日 241 条，包含 09:30 时间点；所有样本时间升序，无重复、空 bar 或 OHLC 包含关系错误。接入已有 240 bar 管线前需明确开盘时点的处理。
- 历史额度初次查询为已用 0、剩余 100；本轮结束已用 3、剩余 97。同一标的跨日期、跨周期没有重复占额。官方规则为最近 7 天按不同标的计额。

## 抽样核对与接入注意

2025-02-05 三个标的分钟汇总成交量、成交额均与同源日线完全一致。浦发和黄金 ETF 的 OHLC 也一致；分众传媒分钟最高/最低为 6.71/6.55，日线为 6.72/6.54，开收盘一致。该高低价差异原因待核对，后续研究接入须保留此质量问题。

本轮直接使用官方 JSON 协议连接 127.0.0.1:11111，只调用连接初始化、历史额度和历史行情。无需新增 Python 依赖。分钟请求原始 beginTime/endTime 都填同一天时返回成功但零条；日期形式 endTime 在本轮分钟结果中表现为当日 00:00 截止，因此取季度使用下一季度首日为终点，单日应使用下一日为终点并过滤日期。日线终点行为不同，不共用这一假设。

## 数据与下一步

- 原始响应：`data/raw/futu/probe_20260910T223928/`（新目录，保留分页响应）。
- 统计与抽样数值：`artifacts/futu_history_probe_20260910/summary.json`。
- 点验脚本：`artifacts/futu_history_probe_20260910/probe.py`。
- 下一步先确定不超过当前剩余额度的小标的池，补齐 2025 至 2026 年缺口；处理每日 241 条口径与分众高低价差异后，再转为研究使用的 clean 数据。

官方参考：[介绍](https://openapi.futunn.com/futu-api-doc/en/intro/intro.html)、[历史 K 线](https://openapi.futunn.com/futu-api-doc/quote/request-history-kline.html)、[额度](https://openapi.futunn.com/futu-api-doc/intro/authority.html)、[JSON 协议](https://openapi.futunn.com/futu-api-doc/en/ftapi/protocol.html)。

## 首批 95 标的补齐完成（2026-09-10 23:47 核对）

23:42 四路下载全部正常退出，95/95 个标的完成，共 380 个年份文件、20,332,929 条 1 分钟记录、84,369 个标的交易日，实际日期 2023-01-03 至 2026-09-10。每个有数据的交易日均为 241 条。额度已用 95、剩余 5。

名单为 80 只个股及现有研究池 15 只 ETF，配置见 `configs/universe/futu_minute_priority_20260910.json`。个股保留此前占额的浦发、分众，其余按截至 2026-09-10 最近 60 个交易日成交额中位数排序，要求至少 50 日观测并排除 ST/退市名称。这是当前下载优先级，不作为历史成分池。

与本地 Tushare 日线核对 70,944 个个股交易日：有成交的日线日期缺失 0；收盘价差异超过 0.01 元为 0；成交量差异超过 1% 为 6 日，成交额差异超过 1% 为 5 日。异常日期见 `artifacts/futu_backfill_20260910/daily_comparison.parquet` 的 `volume_diff > 0.01` 或 `amount_diff > 0.01`。本轮全量交叉核对只覆盖个股，ETF 保留前述抽样证据。

数据入口：

- raw：`data/raw/futu/minute_backfill/symbol=*/year=*/<抓取时间>/page_*.parquet`；重启保留原始抓取，新尝试写新目录。
- clean：`data/clean/futu_minute/futu_minute_priority_20260910/symbol=*/year=*/data.parquet`。
- 完成数字与逐股范围：`artifacts/futu_backfill_20260910/completion.json`、`coverage.parquet`。
- clean 字段：`symbol, bar_time, open, high, low, close, volume, amount, trade_date, is_opening_row, source, adjustment`。`bar_time` 保留供应商时间标签及上海时区，`adjustment=none`；保留 09:30 开盘记录，尚未并入现有 240 bar 因子读取入口。消费时须处理开盘记录并过滤上述量额异常日。

运行入口（Miniforge base 已安装 futu-api 10.10.7008）：

```powershell
D:/Miniforge3/python.exe -m quant.data.futu_minute_backfill --plan configs/universe/futu_minute_priority_20260910.json --output artifacts/futu_backfill_20260910
```

已有完整年份会跳过；可用 `--shard 0 --shards 4` 至 `--shard 3 --shards 4` 做互斥分片，各分片必须使用不同 output 目录，父进程需保持运行至全部退出。5 项定向测试、Ruff、mypy 通过。
