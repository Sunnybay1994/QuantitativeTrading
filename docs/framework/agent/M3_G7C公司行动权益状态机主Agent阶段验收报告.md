# M3 G7C 公司行动权益状态机阶段验收

日期：2026-08-02

## 结论

G7C A 股公司行动 entitlement 纯函数合同已实现，并通过 Windows 与 WSL Miniforge base 定向验证。该阶段建立账户回放所需的双 leg 状态机与严格 mark 原语；尚未形成完整 G7E 模拟器或正式回测 Gate 证据。

## 实现边界

- cash 与 stock leg 独立使用 `NOT_APPLICABLE/CAPTURED/RECOGNIZED/SETTLED`；持久化 position 禁止 `ABSENT`。
- capture 只按 record-close 总持仓生成 entitlement；`record_date < ex_date` 且两者必须属于权威 SH session，重复 event fail closed。
- pay/list 供应商日期映射为首个 `>= due_date` 且不晚于 terminal 的 SH session；超过 terminal 时保留已确认应收，不伪造结算日。
- ex-date 按 event_id、cash-before-stock 顺序确认；settlement 必须从 RECOGNIZED 推进，重复调用幂等，禁止跳步。
- 现金结算按 `ROUND_HALF_UP` 到分，差额显式记录 `cash_rounding_delta`；红股 entitlement 必须精确为整数。
- FULL_DAY 无 bar 的底层 mark 原语只接受 finite、strict-positive Decimal，并计算 `previous_mark / actual_factor_ratio`；不公开 theoretical ex-price API。
- 事件集合、FULL_DAY 停牌 scope 与 reconciliation 唯一性留在 G7E 组合层绑定，不在纯算术原语中重复查询数据。

## 对抗验证

覆盖枚举和值对象冻结、双 leg 独立状态、record-close 数量、周末 due 映射、terminal 外应收、非权威 session、同日确认/结算、重复与跳步、posting 顺序、HALF_UP/delta、整数红股、无效 factor 与核心 import 不加载 Qlib。

```text
Windows pytest: 20 passed in 3.77s
WSL base pytest: 20 passed in 2.70s
Windows Ruff:   All checks passed
Windows mypy:   Success: no issues found in 4 source files
WSL base Ruff:  All checks passed
WSL base mypy:  Success: no issues found in 4 source files
```

## 尚未关闭

- G7D 订单差量、T+1、分板块申报数量与费用；
- G7E 统一账户模拟器及公司行动 reconciliation 组合闭包；
- G7F 三情景发布、正式研究链折级运行和 Linux/ext4 Gate。
