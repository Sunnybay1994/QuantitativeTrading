# M1 HK-HISTORY-R0 港股开盘竞价 OHLC 规范化主 Agent 验证报告

日期：2026-07-18  
结论：**通过；跨市场 Schema 不变，仅规范化港股 open-only 口径差异**

## 1. 实现与理由

`TushareBarMapper` 现在只在 `_market == HK`、原 `high >= low` 且原 close 位于 `[low, high]` 时，把
canonical high/low 扩展到包含 open。该规则保留真实 opening price，也保留下游统一 OHLC 包络；供应商
raw 不修改。

没有全局放宽 `Bar1dSchema`。A 股 open 越界、港股 close 越界、`high < low` 和非正价格继续硬失败，
避免 mapper 把真正的损坏数据修成表面合法。

## 2. 证据与边界

- HKEX 2026-07-10 Daily Quotations 中，`02609.HK` 的 high/low/close、成交量和成交额与 Tushare raw
  一致；该免费表不含 open。
- HKEX 开市前时段资料把最终 IEP 定义为 market opening price；其市场数据字段资料把 opening/closing 与
  high/low 分列。因此“开盘竞价价与连续交易区间口径不同”是高可信解释，但精确 open=3.08 未被 HKEX
  免费日报独立复核，本报告不把推断表述为直接事实。
- `02609.HK` raw high 保持 3.06；mapper 输出 high=3.08、open=3.08，`Bar1dSchema` 通过。

## 3. 验证

WSL Miniforge `base`：

```text
pytest tests/unit/test_tushare_connector.py tests/unit/test_schemas.py -q
43 passed
ruff check src/quant/data/mappers.py tests/unit/test_tushare_connector.py
All checks passed!
mypy src/quant/data/mappers.py
Success: no issues found
```

Windows Miniforge `base` 运行相同 pytest/Ruff：`43 passed`，Ruff 通过。仅有既存 Pandera/Polars
deprecation warning。

本任务只关闭 OHLC 语义阻塞；`02983.HK` 单日缺行、HK60 批量来源与 ETF Instrument 合规来源仍未闭环。
