# M3 G1 合同修订：无 dividend 事件的因子跳变接受为 NO_EVENT

> 状态：已生效（Windows 原生推进；用户授权自行解阻）  
> 命中样本：
> - `000661.SZ` / `2016-04-27`（配股除权「10 配 3」）
> - `600733.SH` / `2018-09-19`（FULL_DAY；ledger stock_ratio=5 与 actual≈3.5 严重不符）

## 背景

G1 v1 公司行动源仅为 Tushare `dividend`。配股/增发等资本事件会驱动 `adj_factor` 跳变；错误或不可对账的 dividend 行也会阻断候选。

## 修订

1. **无事件路径**：接受任意 `actual`（含非分红资本跳变）。
2. **有事件但公式无法闭合**：不再 `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`；回退为 `NO_EVENT_STABLE_FACTOR`（ledger 仍可保留经济事件）。包括：无 prior close、分母非法、actual/declared≤1、market 超差、缺 daily 且非 FULL_DAY、FULL_DAY 但 declared 超差。
3. **有事件且公式闭合**：仍输出 MATCHED_*（含 FULL_DAY 的 NO_MARKET_REFERENCE）。
4. **稳定因子忽略事件**：`abs(actual-1)<=rtol` 时按无事件处理。

禁止用虚构 dividend 解释配股；后续引入配股/增发 SSOT 后再收紧。
