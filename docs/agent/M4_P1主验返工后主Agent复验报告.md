# M4-P1 主验返工后主 Agent 复验报告

日期：2026-07-16  
结论：**不通过，进入二次外部返工闭环**  
范围：幂等查重前的内容 identity 自证

## 1. 已成立部分

外部返工完成聚合结构、事件时序和 broker order id 单次绑定；全新外部初验复现三个返工反例并运行
`tests/unit/test_execution_oms.py` **60 passed**。证据见
[`M4_P1主验返工交付报告.md`](M4_P1主验返工交付报告.md) 与
[`M4_P1主验返工独立初验报告.md`](M4_P1主验返工独立初验报告.md)。

这些结论不覆盖下面的原任务书反例。

## 2. P0：相同 event id 的篡改 payload 被当作 no-op

主 Agent 构造并正常应用一个 ACCEPTED event，随后用 `object.__setattr__` 把同一对象的
`broker_order_id` 从 `B-1` 改为 `B-FORGED`，保留原 `event_id`，再次调用 `reduce_order`。

当前 reducer 的顺序是：类型/command id/quantity → `event_id in applied_event_ids` → 直接返回。它没有在查重前
调用 D0 的内容 identity verifier，因此输出：

```text
FORGED_SAME_EVENT_ID_NOOP_ACCEPTED True B-1
```

聚合没有被改写不等于输入合法；系统已把“相同 id 的不同 payload”错误确认为幂等成功。恢复、gateway 重放或
损坏反序列化对象经过该路径时，冲突会被静默吞掉。

## 3. 初验为何遗漏

独立初验 §4 的 same-event 探针只重复提交同一个未修改合法对象，证明了普通 no-op，却没有按原 P1 反例构造
“同 event id 异 payload”。实现注释“content-hash: same event_id implies same payload”把待验证前提当成事实。

应遵循的通用规则：**内容寻址对象必须先按当前 payload 重算并验证 identity，再执行 membership/idempotency
判断；标识符相等不能替代内容相等。**

## 4. 结论

P1 返工后主验不通过。保持已通过的聚合、时序与 broker identity 修复，不回退；二次返工只关闭输入自证顺序，
见 [`M4_P1主验二次返工任务单.md`](M4_P1主验二次返工任务单.md)。
