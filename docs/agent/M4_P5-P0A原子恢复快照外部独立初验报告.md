# M4-P5-P0A 原子恢复快照外部独立初验报告

- 角色：未参与实现的全新外部独立初验 Agent（`cursor-grok-4.5-high`）
- 日期：2026-08-11
- 工作区：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8ab-prereq`
- 合同：[`M4_P5-P0A原子恢复快照任务单.md`](M4_P5-P0A原子恢复快照任务单.md)
- 设计前提：[`M4_P5-P0恢复与账本持久化前置设计.md`](M4_P5-P0恢复与账本持久化前置设计.md) §2
- 实现报告：[`M4_P5-P0A原子恢复快照实现报告.md`](M4_P5-P0A原子恢复快照实现报告.md)
- 结论：**EXTERNAL PRELIMINARY PASS**（初验通过，可交主 Agent 终验）
- 明确非结论：不宣布 P5/M4/Linux Gate 通过；不替代主验；WSL 证据为 **DrvFS `/mnt/f`**，非 ext4 Gate

## 1. 范围与只读约束

已读：根 `AGENTS.md`、`.ai/README.md`、任务单、实现报告、P5-P0 前置设计 §2、
`src/quant/execution/store.py`（`StoredEventRecord` / `RecoveryRows` / `read_recovery_rows` 与严格 mapper）、
`tests/unit/test_execution_store.py` 中 recovery 相关用例。

本会话仅写入本报告；未改生产代码、未改实现者测试、未改任务/交付文档、未联网、未 `git add/commit`、未跑全量。

当前树中 `RecoveryRows` 已按后续 P0C/cancel/risk 包扩展字段（`ledger_contexts`/`ledger_checkpoints`/
`cancel_*`/`risk_*`），仍为**唯一** snapshot 入口，符合前置设计“不得另建第二个快照入口”。本初验按
P5-P0A 合同核验五类核心行 + 事务一致性 + 失败语义；扩展字段只确认不破坏 P0A 不变量。

## 2. 合同逐项映射

| 成功标准 | 证据 | 判定 |
|---|---|---|
| `StoredEventRecord`、`RecoveryRows`；唯一入口 `ExecutionRepository.read_recovery_rows()` | `store.py` 定义与 `ExecutionRepository.read_recovery_rows`；`__all__` 导出；无第二 list/SQL API | 通过 |
| 须在 `store.transaction()` 内调用；同事务 snapshot；各表主键升序 | repo 仅由 `transaction()` yield；固定 `ORDER BY`；实现者 `test_recovery_rows_*sorted*` / `*_one_transaction_snapshot*`；初验 writer exclusion 再证 | 通过 |
| event/aggregate 验证 command FK；delivery 复用 outbox/command/aggregate join | LEFT JOIN + `_row_to_stored_event` / `_row_to_stored_aggregate` / `_row_to_outbox_delivery`；缺 join → 整体 `ROW_CORRUPT` | 通过 |
| 空库合法 | `test_recovery_rows_empty_store_is_valid` | 通过 |
| 复用 strict mapper；不暴露 connection/cursor/表名/where/order/通用 list | 固定 SQL 字符串；公开面无参数化查询 API | 通过 |
| 不改 schema/migration；不解释 opaque payload；不写 reconciliation/claim/lease | 无 migration 变更于本包职责；payload 原样返回；初验只读探针无 `reconciliation_runs` 写入 | 通过 |
| 损坏行或缺 join → 整体 `ROW_CORRUPT`，无部分结果 | 实现者 broken join / hostile ledger / missing checkpoint tail；初验 orphan event、缺 aggregate delivery | 通过 |
| SQLite 异常 → `RECOVERY_SNAPSHOT_READ_FAILED`；无 SQL/路径/原异常；cause/context 空 | 实现者 hostile SQLite；初验递归 `__cause__` 链脱敏 | 通过 |

## 3. 实现者未使用的对抗性反例

探针：`%TEMP%\p5p0a_adversarial_indep3.py`（不入库）。Windows 与 WSL/DrvFS 均 `BAD_COUNT 0`。

实现者已覆盖：空库、乱序稳定排序、writer exclusion 单事务视图、event/aggregate/delivery/context 缺 join、
hostile ledger/checkpoint、SQLite OperationalError 脱敏。

**本初验新增：**

1. **snapshot 与 ledger/outbox 业务不一致但仍原子**：`cmd-a` 有 delivery、`cmd-b` 无 outbox、另有 orphan ledger → 一次 snapshot 同时可见，不撕裂、不 invent join。
2. **同 id 异 payload**：写路径 `IdempotencyConflict`；离线改 event payload 后 recovery 原样返回 opaque bytes（不解释、不静默折叠）。
3. **事务中断/rollback**：异常回滚后 `read_recovery_rows()` 为空。
4. **重启 replay**：close/reopen 后 snapshot 全等。
5. **unknown event/order**：`get_*` 对未知键返回 `None`；离线 orphan event（缺 command）→ 整体 `ROW_CORRUPT`。
6. **delivery 缺 aggregate**（实现者仅删 outbox）：保留 command+outbox、删 aggregate → `ROW_CORRUPT`。
7. **跨 account/session**：不同 `trusted_root` 同名 URI 互不泄漏。
8. **same-bytes / path alias**：同路径 reopen 字节一致；hardlink（`st_nlink!=1`）两侧 open 均 `URI_PHYSICAL_BOUNDARY_INVALID`（既有叶文件单硬链合同）。
9. **hostile 递归异常脱敏**：三层 `OperationalError.__cause__` 含路径 TOKEN → 对外仅 `RECOVERY_SNAPSHOT_READ_FAILED`，traceback/repr 无 TOKEN，cause/context 空。
10. **zero network / cold import**：冷导入 store；recovery 路径 `socket.create_connection` 调用次数为 0。
11. **只读**：recovery 后仍无 reconciliation run。

## 4. 定向验证命令与结果

Windows `D:\Miniforge3\python.exe`：

- `ruff check` `store.py` + `test_execution_store.py` → **All checks passed!**
- `mypy --no-incremental` `store.py` → **Success: no issues found in 1 source file**
- `pytest -q tests/unit/test_execution_store.py -k "recovery or empty_store or rollback or hardlink or scrubbed"` → **29 passed, 182 deselected**
- 同文件全量定向（非仓库全量）→ **206 passed, 5 skipped**
- 对抗探针 → **BAD_COUNT 0**

WSL Miniforge `base`，路径 `/mnt/f/...`（`df -T` → **drvfs**）：

- 同组 ruff / mypy → 通过
- `pytest -q tests/unit/test_execution_store.py` → **211 passed**
- 同对抗探针 → **BAD_COUNT 0**

说明：实现报告中的 182/186 计数对应当时文件规模；当前 store 测试文件已随后续包增长，计数差不构成违约。

## 5. 初验结论与移交

- 初验：**通过**；P5-P0A 冻结合同、唯一 snapshot 入口、事务一致性、join fail-closed 与脱敏断链均有双平台定向证据与新增对抗探针支撑。
- 未验证/非本包：P5 `recover_local_state` 业务结论、P0B codecs、P0C ledger 语义闭包、WSL/ext4 正式 Gate、全量回归。
- 下一步：主 Agent 终验（SSOT/跨模块不变量/未公开反例/必要回归）。**不得**将本报告表述为 P5 或 M4 Gate 已关闭。
