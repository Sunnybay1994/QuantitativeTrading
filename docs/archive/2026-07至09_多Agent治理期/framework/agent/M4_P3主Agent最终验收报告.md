# M4-P3 主 Agent 最终验收报告

日期：2026-07-17  
结论：**M4-P3 子包最终验收通过**  
边界：不关闭 M4/Gate；只确认事前风控纯函数与输入自证

## 1. 闭环摘要

1. 原 P3 外部闭环后，主验发现未来/过期快照、gross 公式和超 sellable 缺口；
2. 第一轮外部返工与独立初验关闭上述业务规则，但主复验发现 plan/market/account 只比较携带 id，没有按
   当前 payload 重新自证，见 [`M4_P3主验返工后主Agent复验报告.md`](M4_P3主验返工后主Agent复验报告.md)；
3. 第二轮外部实现把 plan、market、account、config 与 counters 自证移到任何经济字段读取之前；
4. 全新外部 Agent 用 market+account 同时篡改、plan intent、counters 与合法输入对抗，独立初验通过，见
   [`M4_P3主验二次返工独立初验报告.md`](M4_P3主验二次返工独立初验报告.md)；
5. 主 Agent 复跑定向测试并执行组合篡改复验。

## 2. 最终验证

```text
WSL Miniforge base
python -m pytest -q tests/unit/test_pretrade_risk.py
→ 33 passed
```

外部实现与独立初验分别复跑目标 Ruff/mypy，均通过；未机械运行无关全量测试。

主 Agent 反例：

| 反例 | 结果 |
|---|---|
| 同时篡改 market quota/rule 与 account sellable，旧 id 全部表面相等 | `MARKET_CONTRACT_INVALID`，无 decision/command |
| 仅篡改 account sellable，market 合法 | `ACCOUNT_CONTRACT_INVALID` |
| 两类错误 | `RiskInputError`；cause/context 均 None；traceback 无注入 payload |

## 3. 最终判定

- 输入在经济消费前按当前 payload 自证，不以携带 id 等值替代内容可信；
- market/account age、quota、suspension、sellable、总仓、单票、日限额、总开关和命令策略形成 fail-closed 顺序；
- SHADOW 不发 command，manual approval 阻断 command；无 approved intent 不伪报成功策略；
- counter 可持久化往返，篡改后重新结构校验。

M4-P3 子包最终验收通过。日计数真实持久化、service/outbox、Paper Gateway 与 M4 Gate 仍未完成。
