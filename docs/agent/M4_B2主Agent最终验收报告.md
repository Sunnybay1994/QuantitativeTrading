# M4-B2 主 Agent 最终验收报告

日期：2026-07-17  
结论：**M4-B2 港股通纯交易规则子包最终验收通过**  
边界：不代表 B1/B3/B4、P2、P4 或 M4 Gate 通过

## 1. 闭环

- 主任务：[`M4_B2港股通纯规则实现任务单.md`](M4_B2港股通纯规则实现任务单.md)
- 首轮实现/初验：[`M4_B2港股通纯规则交付报告.md`](M4_B2港股通纯规则交付报告.md)、
  [`M4_B2港股通纯规则独立初验报告.md`](M4_B2港股通纯规则独立初验报告.md)
- 主验返工：[`M4_B2主验一次返工任务单.md`](M4_B2主验一次返工任务单.md)
- 返工实现/全新独立复验：[`M4_B2主验一次返工交付报告.md`](M4_B2主验一次返工交付报告.md)、
  [`M4_B2主验一次返工独立复验报告.md`](M4_B2主验一次返工独立复验报告.md)

首轮外部初验通过后，主 Agent 发现 D0 合法 finite Decimal 极值可使 tick 除法抛 `decimal.Overflow`。返工将
tick 判定改为 coefficient/exponent 的精确整数关系，大正指数差使用 modular pow，不依赖 Decimal context；
全新外部复验增加非 1 coefficient、负指数尾零边界和 hostile context 连续调用三组反例，均通过。

## 2. 最终合同

- 五个输入先重建自证，再读取经济字段；篡改统一为脱敏 `ConnectRuleInputError`，cause/context 为空；
- 仅接受 HK/HKD 且 symbol/session/route/position 关联一致；
- 双市场与 connect 通道任一关闭即拒绝；港股通不施加 A 股 T+1，卖单使用已验证 sellable；
- quota 仅阻止 BUY，SELL 不受额度耗尽误伤；
- BUY 必须 per-symbol 整手；SELL 允许整手或小于一手的纯碎股，禁止单笔混合 lot；
- tick 精确整除且不 rounding；ELO 可申报上下界任一缺失即 fail closed，边界 inclusive；
- 规则有效期和 state rule version 显式匹配；所有经济拒绝 code 来自 `ExecutionRejectReason` SSOT；
- 纯内存、无 IO/网络/data 扫描/费用/FX/账本/Gateway。

## 3. 主 Agent 验证

```text
python -m pytest \
  tests/unit/test_connect_execution.py tests/unit/test_execution_contracts.py -q
→ 32 passed in 1.46s
```

重放原主验反例：

```text
limit_price = Decimal("1E+999999")
tick_size   = Decimal("1E-999999")
公共 evaluate_connect_intent → ACCEPTED
B2_MAIN_DECIMAL_REPRO_CLOSED
```

结果无异常，`normalized_limit_price` 保持输入精确值。外部复验另确认 Ruff/mypy 通过，原 31 项无回归。

## 4. 已知边界

- 本包是日频 PAPER/SHADOW 的规则纯函数，不提供实时行情；HK `limit_down/limit_up` 必须由上游 repository
  作为评估时点已验证的 ELO 可申报价格带提供，不能用 previous close 伪造；
- board lot、tick 与 rule version 均来自 verified state/配置，不硬编码 2026 规则；
- order planning、费用/FX、结算账本和 Paper Gateway 仍由后续包交付；
- 以上限制不阻断 B2 子包，但 M4 总闭环尚未完成。

