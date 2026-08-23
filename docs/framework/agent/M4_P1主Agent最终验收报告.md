# M4-P1 主 Agent 最终验收报告

日期：2026-07-17  
结论：**M4-P1 子包最终验收通过**  
边界：不关闭 M4/Gate；只确认纯内存 OMS reducer 合同

## 1. 闭环摘要

1. 原 P1 外部闭环后，主验发现聚合可伪造、事件倒序和 broker id 漂移；
2. 第一轮外部返工与独立初验关闭上述三项，但主复验发现相同 event id 的篡改 payload 在 identity 自证前被
   静默 no-op，见 [`M4_P1主验返工后主Agent复验报告.md`](M4_P1主验返工后主Agent复验报告.md)；
3. 第二轮外部实现把 aggregate、nested intent、command、event 的自证移到 membership/no-op 之前；
4. 全新外部 Agent 用双字段组合篡改、nested intent、非法 aggregate 和合法 duplicate 对抗，独立初验通过，见
   [`M4_P1主验二次返工独立初验报告.md`](M4_P1主验二次返工独立初验报告.md)；
5. 主 Agent 在当前工作树执行最终定向与未公开反例复验。

## 2. 最终验证

```text
WSL Miniforge base
python -m pytest -q tests/unit/test_execution_oms.py
→ 69 passed
```

外部实现与独立初验分别复跑目标 Ruff/mypy，均通过；未运行无关全量测试。

主 Agent 未公开反例：

| 反例 | 结果 |
|---|---|
| 已应用 event 同时篡改 broker id 与 occurred_at、保留旧 event id | `OmsError`；cause/context 均 None；无注入值泄漏 |
| 篡改 command 内嵌 intent limit price、保留 intent/command id | `OmsError`，在状态处理前拒绝 |
| 篡改已应用 aggregate 的 filled quantity，再提交已见 event | `OmsError`，不进入 no-op |
| 未篡改合法 duplicate | 返回原 aggregate 对象，时间与 event 集合不变 |

## 3. 最终判定

- 聚合状态、数量、event 集合和最后事件时间形成结构闭包；
- 新事件时序非递减，累计成交严格单调，broker order id 至多绑定一次；
- 内容寻址输入按当前 payload 自证后才允许幂等 no-op；
- 失败为稳定脱敏 `OmsError`，无 DB/network IO。

M4-P1 子包最终验收通过。Paper Gateway、durable recovery、reconciliation 和 M4 Gate 仍未完成。
