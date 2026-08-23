# M4-D0 主 Agent 最终验收报告

日期：2026-07-16  
结论：**M4-D0 子包最终验收通过**  
边界：不关闭 M4/Gate；只确认交易领域合同及与当前 OMS 的接口合流

## 1. 闭环链路

1. 原外部闭环后，主验发现 plan 嵌套来源、event 真实数量、snapshot 日期和非法 spec 错误边界缺口，见
   [`M4_D0主Agent终验报告.md`](M4_D0主Agent终验报告.md)；
2. 外部实现按 [`M4_D0主验返工任务单.md`](M4_D0主验返工任务单.md) 完成 F1–F4；
3. 全新外部 Agent 独立复现四个主验反例并增加混合错误 element 对抗，全部通过，见
   [`M4_D0主验返工独立初验报告.md`](M4_D0主验返工独立初验报告.md)；
4. P1 随后在不修改 contracts 的前提下扩展 OMS 聚合合同；主 Agent 在当前合流工作树复跑 D0 contracts 与新版
   OMS，确认接口未回退。

## 2. 最终验证

```text
WSL Miniforge base
python -m pytest -q tests/unit/test_execution_contracts.py
→ 17 passed

python -m pytest -q tests/unit/test_execution_contracts.py tests/unit/test_execution_oms.py
→ 77 passed
```

外部实现和独立初验分别复跑目标 Ruff/mypy，均通过；本次未运行无关全量测试。

主 Agent 核对的核心闭包：

- `OrderPlan` 顶层四 identity 与每个 intent 双向一致，builder 和直接构造/replace 均不能绕过；
- `ExecutionEvent` 公开 builder 必须接受真实 `OrderCommand`，累计数量不能超过真实 command quantity；
- market snapshot 的每个 state 与 snapshot `session_date` 一致；
- spec 和 sequence element 在排序、哈希或属性访问前进行合同门禁，错误稳定为 `ContractError`；
- 新版 OMS 仍使用 D0 的真实 command/event 入口，未恢复裸 `command_quantity` 或伪造 identity 路径。

## 3. 最终判定

四个主验缺口、独立混合反例和 D0→P1 合流回归均通过，M4-D0 子包最终验收通过。该结论不代表 OMS P1、
持久化、风控、paper gateway 或 M4 Gate 已完成。
