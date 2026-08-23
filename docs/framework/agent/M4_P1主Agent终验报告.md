# M4-P1 主 Agent 终验报告

日期：2026-07-16  
结论：**不通过，待外部返工闭环**  
范围：纯内存 OMS 聚合合同、事件时序与券商订单身份闭包

## 1. 证据

- 冻结合同：[`M4轻量交易闭环分包任务书.md`](M4轻量交易闭环分包任务书.md) M4-P1。
- 外部交付与初验：[`M4_P1_OMS状态机交付报告.md`](M4_P1_OMS状态机交付报告.md)、
  [`M4_P1_OMS状态机独立初验报告.md`](M4_P1_OMS状态机独立初验报告.md)。
- D0 返工合流后，主 Agent 复跑 `tests/unit/test_execution_oms.py`：**20 passed**。
- 以下为既有实现与独立初验未覆盖的三个状态恢复/对账反例。

## 2. 主验反例

### P0-A：公开聚合对象可表达不可能状态

调用方可直接构造 `FILLED + filled_quantity=999 + reject_code=bad + 非 hex event id` 的
`OrderAggregate`，对象不做任何结构或跨字段自证。恢复流程若接受该对象，后续 reducer 的状态判断建立在伪造
投影上。

结果：`FORGED_AGGREGATE_ACCEPTED 999`。

### P0-B：较早事件可倒序推进状态

先在 `02:05` 应用 `ACCEPTED`，再应用 `02:04` 的 `PARTIAL_FILL`，reducer 接受并把累计成交推进到 40。
当前聚合不保留最后事件时间，因此无法在重放乱序、迟到或损坏事件时 fail closed。

结果：`REVERSE_TIME_ACCEPTED 40`。

### P0-C：券商订单身份可静默漂移

聚合先由 `broker_order_id=B-1` 的 ACCEPTED 建立，随后 `broker_order_id=B-2` 的成交事件被接受，聚合身份静默
替换为 B-2。同一 command 的 broker order 身份必须至多从未知绑定一次，不能在事件流中改写。

结果：`BROKER_ID_CHANGE_ACCEPTED B-2`。

## 3. 结论

现有状态转移、累计成交和 event-id 幂等测试是绿色的，但聚合输入、事件时间和外部订单身份尚未形成可恢复
闭包。P1 **主验不通过**；返工边界见 [`M4_P1主验返工任务单.md`](M4_P1主验返工任务单.md)。
