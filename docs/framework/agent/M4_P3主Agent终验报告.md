# M4-P3 主 Agent 终验报告

日期：2026-07-16  
结论：**不通过，退回外部返工闭环**  
范围：事前风控的数据时点、总仓暴露与可卖数量

## 1. 证据

- 冻结合同：[`M4轻量交易闭环分包任务书.md`](M4轻量交易闭环分包任务书.md) M4-P3。
- 外部交付与初验：[`M4_P3事前风控交付报告.md`](M4_P3事前风控交付报告.md)、
  [`M4_P3事前风控独立初验报告.md`](M4_P3事前风控独立初验报告.md)。
- 主 Agent 复跑 `tests/unit/test_pretrade_risk.py`：**12 passed**。
- 以下反例均使用内存小对象，无网络和大数据。

## 2. 主验反例

### P0-A：示例配置会拒绝所有第一笔买入

实现把 `equity + batch_buy_notional` 当作 projected gross。现金也因此被算作持仓暴露；仓库示例配置
`max_gross_exposure=1.0` 下，全现金账户买入 100 股、名义 1000 元也得到
`MAX_GROSS_EXPOSURE`，没有任何 approved intent。

结果：`EXAMPLE_SMALL_BUY_ACCEPTED False`。

总仓暴露应以证券持仓绝对市值为分子，现金只参与净资产/权益分母；批次订单在现有持仓上投影后再计算。

### P0-B：未来行情快照被视为新鲜

`now=03:00`、`market.as_of=04:00` 时，age 为负数，而实现仅检查 `age <= max_age`，因此放行买入并生成
PAPER command。

结果：`FUTURE_SNAPSHOT_ACCEPTED True`。

### P0-C：过期账户快照仍可生成买单

`snapshot_max_age_seconds=60`、`now=03:00`、`account.as_of=01:00` 时，市场快照虽新鲜，但账户现金与持仓已
过期，风控仍接受并生成 command。

结果：`STALE_ACCOUNT_ACCEPTED True`。

### P0-D：卖出数量可超过 sellable quantity

账户持仓 200 股、可卖仅 50 股，计划卖出 100 股，风控仍通过并生成一条 command。

结果：`OVERSELL_ACCEPTED True 1`。

## 3. 非阻塞记录

没有任何 approved intent 时，当前代码仍可追加 `MANUAL_APPROVAL_REQUIRED`。这会让审计语义略显混乱，但不
直接产生 command，本轮只要求顺带在最小修改内校正，不单独扩大为新抽象。

## 4. 结论

现有优先级、总开关和日计数反例覆盖较好，但默认总仓公式与账户/卖出防线会阻断合法买入或放行不可执行卖单。
P3 **主验不通过**；返工任务见 [`M4_P3主验返工任务单.md`](M4_P3主验返工任务单.md)。
