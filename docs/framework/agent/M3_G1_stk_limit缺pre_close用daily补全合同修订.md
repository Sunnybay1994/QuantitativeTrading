# M3 G1 合同修订：`stk_limit` 缺 `pre_close` 时用同日 `daily.pre_close` 补全

> 状态：已生效（Windows 原生推进 full candidate 解阻；用户授权自行解决阻碍）  
> 方法版本字符串：仍为 `tushare_stk_limit_suspension_aware_v1`（不 bump，避免冻结 plan 身份漂移）

## 背景

正式 HISTORY raw 中存在开市日 `stk_limit` 行：`up_limit`/`down_limit` 为正 finite，但 `pre_close=null`（样本日 `2024-07-23`，如 `000001.SZ`）。同日 `daily` 有合法 `pre_close`，日历 `is_open=true`，且非 FULL_DAY 停牌。

旧规则把「`pre_close` null/0」一律当作 sentinel 省略，导致 `require_g1_price_limit_coverage` 报 `G1_PRICE_LIMIT_UNPROVEN`。

另有一类覆盖域缺口：日历开市日既无 `daily` 也无可用 limit（或仅有 sentinel limit），且 `suspend_d` 未标 FULL_DAY。无 OHLC 则当日不可成交。

## 修订

1. **空 sentinel（仍省略）**：`pre_close` null/0，且上下限均为 null 或 0。
2. **可修复行**：`pre_close` null/0，但上下限均为正 finite；若提供同日 `daily.pre_close` 且满足 `down_limit < daily.pre_close < up_limit`，则发出 clean `PriceLimit1d`（`has_price_limit=True`），`pre_close` 取自 daily，**上下限仍取自 `stk_limit`**。
3. **失败闭包**：提供了 lookup，但 daily `pre_close` 不落在上下限之间 → `G1_EXECUTION_FACT_VALUE_INVALID`。
4. **无 bar 豁免**：`require_g1_price_limit_coverage` 新增必填 `bars`；与 FULL_DAY 相同，无同日 bar 的 key 不进入 required（无成交证据）。
5. **禁止**：不发明涨跌停价；不把 sentinel 解释为无限制日；不输出 `has_price_limit=False`；不静默用中点等推算值。

实现入口：`build_g1_daily_pre_close_lookup` + `map_g1_price_limit_response(..., daily_pre_close=...)`；candidate / release / 零网络诊断路径必须传入 lookup 与 bars。
