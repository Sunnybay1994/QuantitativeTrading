# M4 P4-P0 可恢复 Transactional Outbox 存储前置主 Agent 最终验收报告

日期：2026-07-18  
结论：**P4-P0 SQLite v2 delivery/claim/lease/terminal 存储前置最终验收通过**  
边界：不实现 P4 service/P2 Gateway，不关闭 P4 或任何 M4 Gate

## 1. 闭环证据

- 冻结任务：[`M4_P4-P0可恢复TransactionalOutbox存储前置任务单.md`](M4_P4-P0可恢复TransactionalOutbox存储前置任务单.md)
- 临时流程：用户已在 24 小时内暂停外部 Cursor 流程，本包由主 Agent 实现；内部子 Agent 只读独立对抗。
- 独立审查首次发现两项真实问题：batch claim 依赖异常逃出外层事务才能全回滚，以及 `from None` 未实际
  清空损坏 enum 的 `__context__`。返工后审查者以全新临时数据库复验原反例，并新增“两个 UPDATE 均成功、
  post-update SELECT 失败”的 savepoint 反例，最终结论通过。

## 2. 实现与合同复核

修改：

- `src/quant/execution/migrations/v002_outbox_delivery.py`：新增非破坏性 v2 delivery 表、双 command/aggregate
  外键、严格状态 CHECK 和 pending/expired-lease partial indexes；不回填 v1 outbox。
- `src/quant/execution/migrations/__init__.py`：注册 v2 migration。
- `src/quant/execution/store.py`：新增严格 UTC delivery 对象与 typed repository API；deterministic claim、lease
  fencing、`SENT/UNKNOWN` 终态、稳定 `TX_BUSY`、全行闭包预检和方法级 SAVEPOINT 原子性。
- `tests/unit/test_execution_store.py`：新增迁移、恢复、并发、损坏行、异常断链和跨平台反例；Windows 无
  symlink privilege 时只对 WinError 1314 精确 skip，Linux Gate 仍实际执行对应边界。

关键不变量：

- command、aggregate、outbox、delivery 缺任一项都不能形成可 claim 行；旧 outbox 不会因 migration 静默发送。
- `attempt_count` 同时是 fencing generation；mark 必须匹配 owner + attempt，同名重启 worker 的旧 attempt
  也不能迟到落终态。
- lease 在 `lease_until <= now` 时可重领；旧 owner 的 `terminal_at >= lease_until` 被拒绝。
- `SENT/UNKNOWN` 保留最后 owner/lease/attempt/terminal 审计信息，普通 claim 永不返回终态；相同终态参数
  no-op，异参数和跨终态覆盖 fail closed。
- claim 先验证全部 delivery/LEFT JOIN 闭包和 attempt 上界，再在内部 SAVEPOINT 完成整批 UPDATE 与重读；
  即使调用方在外层 transaction 内捕获异常，也不会提交部分 claim。
- SQLite busy 采用 `timeout=0` 和稳定 `TX_BUSY`；同一 store 嵌套 writer 也 fail fast。
- 新增映射错误在离开底层 except 后抛出，实际满足 `__cause__ is None`、`__context__ is None`，不只依赖
  suppressed traceback。

## 3. 主 Agent 与独立验证

WSL Miniforge `base`：

```text
python -B -m pytest tests/unit/test_execution_store.py -q -p no:cacheprovider
149 passed in 6.37s

ruff check src/quant/execution/store.py src/quant/execution/migrations tests/unit/test_execution_store.py
All checks passed!

mypy src/quant/execution/store.py src/quant/execution/migrations
Success: no issues found in 4 source files
```

Windows Miniforge `base`：

```text
python -B -m pytest tests/unit/test_execution_store.py -q -p no:cacheprovider
144 passed, 5 skipped in 8.28s

Ruff: passed
mypy: passed (4 source files)
```

五个 Windows skip 均为当前账户缺少 symlink/相关文件系统权限；同组测试在 WSL 实际执行并通过。独立审查
额外临时探针输出：

```text
PASS_ORIGINAL_EXHAUSTION_ATOMIC
PASS_ORIGINAL_EXCEPTION_CHAIN
PASS_FRESH_REREAD_ROLLBACK_RELEASE_AND_EMPTY
```

## 4. 合流与剩余风险

首次扩大到 execution 六个直接测试文件时，store/contract/port/risk/route 等 287 项通过，但 OMS 的 41 个
test 函数因旧 helper 未传新增必填 `connect_route` 而在进入 OMS 前 TypeError。该 Route 合流测试漂移已按
[`M4_P1Route参数测试漂移返工验证报告.md`](M4_P1Route参数测试漂移返工验证报告.md) 独立修复；生产合同/OMS
未改。修复后合流结果：WSL `331 passed`，Ruff 与 7 个相关生产源码 mypy 通过；Windows
`326 passed, 5 skipped`，Ruff 通过。

本包只提供 P4/P5 所需的可恢复存储原语。真实 dispatch 的 wire format、Gateway timeout 处置调用、planner、
账本、reconciliation 和四周 PAPER/SHADOW 证据仍未实现；Windows 与 WSL 也禁止用路径别名同时打开同一
SQLite 文件。
