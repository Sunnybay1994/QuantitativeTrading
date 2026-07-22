# M4-P0 主 Agent 终验报告

日期：2026-07-16  
结论：**不通过，退回外部返工闭环**  
范围：SQLite URI、migration/store 错误边界、durable identity 与 command-event 关系

## 1. 证据

- 冻结合同：[`M4轻量交易闭环分包任务书.md`](M4轻量交易闭环分包任务书.md) M4-C0、§2、M4-P0。
- 外部交付、初验与复验：[`M4_P0持久化交付报告.md`](M4_P0持久化交付报告.md)、
  [`M4_P0持久化独立初验报告.md`](M4_P0持久化独立初验报告.md)、
  [`M4_P0持久化独立复验报告.md`](M4_P0持久化独立复验报告.md)。
- 主 Agent 复跑 `tests/unit/test_execution_store.py`：**10 passed**。
- 初验发现的同 event ID 异 command ID 已关闭；以下是未被复验覆盖的新边界。

## 2. 主验反例

### P1-A：store 直接接受绝对 SQLite URI

`ExecutionStore.open("sqlite:////tmp/.../absolute.db")` 成功建库。P0 把绝对 URI 称为设计，但 C0 的权威配置
合同明确 SQLite 只能是项目相对安全路径；公开 store 入口不能提供绕过上游安全门禁的第二条路径。

结果：`ABSOLUTE_URI_ACCEPTED True`。

### P1-B：durable identity 接受任意字符串

`put_command(identity="not-a-hash")` 成功。M4 identity 统一为 canonical 裸 64 lowercase hex；storage 可以不理解
payload 业务类型，但至少必须拒绝不符合 identity wire format 的值。

结果：`NON_HEX_IDENTITY_ACCEPTED True`。

### P1-C：events 表允许 orphan command

未写入 command 时，`put_event(command_id="missing-command", ...)` 成功。代码启用了 `PRAGMA foreign_keys=ON`，
但 v001 没有声明外键，typed repository 也不做存在性门禁。

结果：`ORPHAN_EVENT_ACCEPTED True`。

### P0-D：建库/打开错误未统一脱敏

- parent 是普通文件时，`Path.mkdir` 在 try 外直接外溢 `FileExistsError` 和绝对路径；
- SQLite open 失败虽映射 `StoreError("OPEN_FAILED")`，却使用 `raise ... from exc` 保留底层 cause。

结果：`MKDIR_ERROR_LEAK FileExistsError True False False`；
`OPEN_ERROR_CAUSE StoreError False True OperationalError`。

## 3. 结论

P0 的既有 10 项测试和一次返工只覆盖行内容幂等，尚未关闭 URI、identity、关系完整性和 I/O 脱敏边界。
当前为**主验不通过、待返工**。任务见 [`M4_P0主验返工任务单.md`](M4_P0主验返工任务单.md)。
