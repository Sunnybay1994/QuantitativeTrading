# M4-P4-R-R1：确认范围内精确订单派发任务单

日期：2026-08-02  
状态：实现、外部独立初验与主 Agent 最终验收均已通过；仅关闭确认范围内精确订单派发子合同

## 目标与不变量

为 P6 `paper-submit` 补齐精确派发原语。现有
`ExecutionService.dispatch_pending(limit)` 按全局 ready 队列领取；操作员确认某个计划后，若并发产生新的
pending command，单靠 `limit` 不能证明实际跨越 PAPER gateway 的仍是被确认集合。

本包新增 exact allowlist 派发：调用方必须给出排序、唯一、非空的 `command_ids`；store 在单个
`BEGIN IMMEDIATE` 事务中验证这些 command 的 command/outbox/delivery 闭包全部存在且全部可领取，随后只领取该集合。
任一元素不满足时整个事务回滚，零部分 lease、零 gateway 调用。集合外 command 即使更早、更旧或并发新增，也绝不被领取。

本包不实现 CLI、审批、cancel、broker query 或 live gateway；不改变现有全局 worker 的
`dispatch_pending(limit)` 行为。

## 公共接口

`ExecutionRepository` 新增：

```python
def claim_selected_outbox_deliveries(
    self,
    *,
    command_ids: tuple[str, ...],
    worker_id: str,
    now: datetime,
    lease_until: datetime,
) -> tuple[OutboxDelivery, ...]: ...
```

`ExecutionService` 新增：

```python
def dispatch_commands(self, *, command_ids: tuple[str, ...]) -> DispatchResult: ...
```

`command_ids` 必须按字典序排序、唯一、非空且每项为现有 canonical command id。错误统一翻译为稳定、脱敏
`ExecutionServiceError`。store 方法只在 `ExecutionStore.transaction()` 内可调用；返回顺序与输入完全一致。

## 原子与失败语义

1. 每个选中 delivery 必须为 `PENDING`，或 lease 已严格过期的 `LEASED`；`SENT/UNKNOWN`、未过期 lease、缺行、
   command/outbox 断链均导致固定失败，整批零更新。
2. 同一事务先完成全部闭包与可领取验证，再更新全部 selected rows；更新 rowcount 不等于集合大小时抛 CAS 冲突并回滚。
3. `dispatch_commands` 只能消费 selected claim 的返回，不得回退调用全局 claim；后续 gateway/OMS/ledger 语义复用现有
   `dispatch_pending` 的同一私有实现，不复制第二套 reducer 或回调事务。
4. gateway 前 lease fence、SENT/UNKNOWN/NOT_SENT、callback transaction failure 语义保持不变。
5. 本包只支持 `ExecutionMode.PAPER` 的现有 durable commands；不存在任何 live 分支或 SDK import。

## 白名单

- `src/quant/execution/store.py`
- `src/quant/execution/service.py`
- `tests/unit/test_execution_store.py`
- `tests/unit/test_execution_service.py`
- 本任务单、交付报告、独立初验报告

## 必测反例

1. A/B 已确认，同时插入更早排序的 C：精确派发只调用 A/B，C 保持原字节。
2. A 可领取、B 已 SENT/UNKNOWN/被其他 worker 持有/断链：A/B 均不 lease，gateway 零调用。
3. 空、乱序、重复、伪 command id：稳定失败且 cause/context/object graph 不含输入或底层异常。
4. 两 worker 同时领取同一 exact set：至多一个成功，经济回调不重复。
5. 现有 `dispatch_pending(limit)` 回归、恢复闭包、ledger checkpoint 与 callback transaction 继续通过。

## 验收

- Windows 定向 Ruff、mypy、pytest；
- WSL Miniforge base 对应定向验证（Windows 结果不替代 Linux Gate）；
- 独立复验增加实现者未覆盖的并发插入或部分不可领取反例；
- 本包通过只关闭 P4-R 工程前置，不关闭 P6、P8、PAPER soak 或 M4。
