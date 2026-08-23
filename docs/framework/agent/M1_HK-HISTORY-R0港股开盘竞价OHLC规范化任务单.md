# M1 HK-HISTORY-R0 港股开盘竞价 OHLC 规范化任务单

日期：2026-07-18  
执行者：主 Agent（24 小时简化流程；内部只读审计与主 Agent 实现）  
状态：已完成

## 1. 现象与目标

单次 `hk_daily(trade_date=20260710)` raw 中，`02609.HK` 为 `open=3.08, high=3.06, low=2.92,
close=2.96`。HKEX 官方当日 Daily Quotations 对 high/low/close、成交量和成交额给出相同值，但该官方
免费表不含 open。HKEX 开市前时段说明把最终 IEP 定义为 market opening price；其市场数据资料又把
opening/closing 与 high/low 列为独立字段。因此这是港股开盘竞价与连续交易 high/low 口径分离的高可信
反例，不是可用浮点容差掩盖的误差。

目标是在不放宽跨市场 `Bar1dSchema`、不修改 raw 的前提下，把 canonical OHLC 区间显式扩展到包含港股
opening price，保留下游对 `low <= open/close <= high` 的统一不变量。

## 2. 冻结规则

- 只作用于 `TushareBarMapper` 且 `_market == HK`。
- 只有原 `high >= low` 且原 `close` 位于 `[low, high]` 时，允许
  `canonical_high=max(raw_high, raw_open)`、`canonical_low=min(raw_low, raw_open)`。
- A 股 open 越界不修正；港股 close 越界、`high < low`、非正价格不修正，继续由 Schema 硬失败。
- raw snapshot 和供应商字段保持不变；不得把精确 `open=3.08` 宣称为已由 HKEX 免费日报独立核实。
- 不改变金额、成交量、复权或 source 语义。

## 3. 反例与通过条件

- `02609.HK` 回归：raw high 仍为 3.06，clean high 为 3.08，Schema 通过。
- HK open 低于 raw low 时只扩展 low。
- A 股 open>high、HK close>high、HK high<low 均仍被 Schema 拒绝。
- WSL Miniforge base 与 Windows Miniforge 定向 pytest/Ruff 通过；WSL 定向 mypy 通过。

验证证据见
[`M1_HK-HISTORY-R0港股开盘竞价OHLC规范化主Agent验证报告.md`](M1_HK-HISTORY-R0港股开盘竞价OHLC规范化主Agent验证报告.md)。
