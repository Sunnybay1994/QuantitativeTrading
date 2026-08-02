# M4-P5-P0A 原子恢复快照实现报告

状态：实现与自验完成，待独立初验及主验；不代表 P5、M4 或 Linux Gate 通过。

## 交付

- `StoredEventRecord` 保留 event-command foreign-key closure。
- `RecoveryRows` 是一次 transaction-consistent 的 immutable snapshot。
- `ExecutionRepository.read_recovery_rows()` 以固定 SQL、固定表集合和各自主键升序读取；command/event/
  aggregate/delivery/ledger 全部通过既有严格 mapper 或新增窄 event/aggregate mapper。
- event 与 aggregate 使用 command LEFT JOIN，delivery 复用既有 outbox/command/aggregate join columns；缺失关联行整体
  `ROW_CORRUPT`。SQLite error 映射为脱敏、断链的 `RECOVERY_SNAPSHOT_READ_FAILED`。

未增加通用 SQL/list API，未修改 migration/schema，未预实现 ledger context/checkpoint，也未解释 payload。

## 验证

Windows `D:\Miniforge3\python.exe`：

- Ruff（store + store tests）：通过；
- mypy（生产 `store.py`）：通过；全量历史 store test 文件在当前 Windows mypy 2.3.0 中仍有 4 个既有
  platform/mock typing error，与本包新增行无关；
- `tests/unit/test_execution_store.py`：182 passed, 5 skipped；仅既有 pytest cache WinError 5 warning。

WSL Miniforge base：Ruff 通过；生产 `store.py` mypy 通过；同一 store test 文件为 186 passed, 1 skipped。
新增测试覆盖空库、稳定排序、writer exclusion 下的单事务一致视图、损坏 event/aggregate/delivery join、hostile
SQLite exception 脱敏与 cause/context 断链。

## 剩余边界

P5 仍等待 P5-P0B public canonical codecs 和 P5-P0C ledger context/checkpoint 事务闭包。RecoveryRows 目前只
承载既有五类表，不推断业务 reconciliation 结论。
