# M4-P3 主验返工后主 Agent 复验报告

日期：2026-07-16  
结论：**不通过，进入二次外部返工闭环**  
范围：风控读取经济字段前的输入内容 identity 自证

## 1. 第一轮返工已成立部分

外部实现已按第一轮任务修正未来/过期快照、总仓暴露、sellable quantity 和空审批审计，定向自测
`tests/unit/test_pretrade_risk.py` **25 passed**。这些修复保持，不回退。

## 2. 新主验反例

### P0-A：篡改 market quota 后仍生成买单

先以 `buy_quota_available=False` 构造 verified market snapshot 与绑定该 snapshot id 的 plan，再用
`object.__setattr__` 把同一 state 改为 `True`，保留旧 snapshot id。当前 `evaluate_pretrade` 只比较
`plan.market_snapshot_id == market.snapshot_id`，不按当前 states 重算 snapshot identity，因此接受并生成 command：

```text
FORGED_MARKET_QUOTA_ACCEPTED True 1
```

### P0-B：篡改 account sellable 后绕过超卖

以 `quantity=200, sellable_quantity=50` 构造 account snapshot 与卖出 100 股的 plan，再把 position 的
`sellable_quantity` 改成 100，保留旧 account snapshot id。风控把篡改值当真并生成 command：

```text
FORGED_ACCOUNT_SELLABLE_ACCEPTED True 1
```

## 3. 根因与规则

D0 已提供 plan、verified market snapshot、account snapshot 的公开 identity verifier；P3 没有在风险判断前调用，
把 frozen dataclass 的历史构造成功误当成当前 payload 仍可信。

应遵循的通用规则：**任何会影响经济行为的内容寻址输入，都必须在消费边界按当前 payload 重算 identity；只比较
调用方携带的两个 id 相等，不能证明任一 payload 未被损坏。**

## 4. 结论

P3 第一轮返工后主复验不通过。二次返工只补输入自证和稳定失败语义，见
[`M4_P3主验二次返工任务单.md`](M4_P3主验二次返工任务单.md)。
