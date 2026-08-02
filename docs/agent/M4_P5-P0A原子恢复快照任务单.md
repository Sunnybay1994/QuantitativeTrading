# M4-P5-P0A 原子恢复快照任务单

状态：冻结实现边界；本包只提供 P5 的 typed read prerequisite，不关闭 P5/M4/Linux Gate。

## 目标与接口

在 `quant.execution.store` 新增 frozen `StoredEventRecord`、`RecoveryRows`，以及唯一入口：

```python
ExecutionRepository.read_recovery_rows() -> RecoveryRows
```

调用方必须在单个 `ExecutionStore.transaction()` 内调用。返回 commands、events、order aggregates、outbox
deliveries、ledger entries，各 tuple 按主键升序。event 与 aggregate 都保留并验证 command foreign key；
delivery 复用现有 outbox/command/aggregate join closure。空库合法。

## 约束与失败语义

- 复用 strict row mapper；不得暴露 connection/cursor、表名、where/order 参数或通用 list API。
- 本包不改 schema/migration，不实现 ledger context/checkpoint，不解释 opaque payload。
- 任一损坏行或缺 join 使整个 snapshot `ROW_CORRUPT`，不返回部分结果。
- SQLite 读取异常稳定映射为 `RECOVERY_SNAPSHOT_READ_FAILED`；不得泄露 SQL、路径或原异常，cause/context
  均为空。
- 只读 snapshot 不 claim、不续 lease、不修复或写 reconciliation run。

## 白名单与验收

- `src/quant/execution/store.py`
- `tests/unit/test_execution_store.py`
- 本任务单与 `M4_P5-P0A原子恢复快照实现报告.md`

至少覆盖空库、乱序插入后的稳定排序、同 transaction snapshot、损坏 event/aggregate/delivery join 整体失败、hostile
SQLite error 脱敏断链。Windows 与 WSL base 执行定向 Ruff、mypy、pytest；平台绿测不替代更高 Gate。
