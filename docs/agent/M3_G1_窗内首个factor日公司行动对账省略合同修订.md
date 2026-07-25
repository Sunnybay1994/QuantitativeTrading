# M3 G1 合同修订：窗内首个 factor 日 / 无 prior bar 的公司行动对账省略

> 状态：已生效（Windows 原生推进；用户授权自行解阻）  
> 命中样本：
> - `300182.SZ` / `ex_date=2015-10-09`（恰为 HISTORY 窗内该标的首个 `adj_factor` 日）
> - `000553.SZ` / `ex_date=2016-06-15`（FULL_DAY；首根 bar=`2016-10-17`，无 prior close）

## 规则

1. **首个 factor 日**：若 `ex_date == factors_by_symbol[symbol][0].effective_date`，事件不进入对账匹配。
2. **无 prior bar**：若 bars 中不存在严格早于 `ex_date` 的 close，事件不进入对账匹配（declared/market 公式不可构造）。
3. **FULL_DAY + 无 prior bar 的因子跳变**：无事件匹配且 `actual` 相对 1 超 rtol 时，若 `effective_date` 为 FULL_DAY 且窗内无更早 bar，接受为 `NO_EVENT_STABLE_FACTOR`（ledger 可仍保留经济事件）。
4. **因子未跳变**：若相邻 factor 的 `actual` 相对 1 在 rtol 内，即使 ledger 有同日事件，也按无事件处理（样本 `000627.SZ@2022-06-02`，cash 事件但 adj_factor 未变）。

禁止发明窗外 prior close / prior factor。
