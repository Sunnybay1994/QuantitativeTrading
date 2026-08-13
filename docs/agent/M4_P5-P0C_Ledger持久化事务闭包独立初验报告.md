# M4-P5-P0C Ledger 持久化事务闭包独立初验报告

日期：2026-08-02  
结论：**FAIL**

## 结论摘要

schema v3→v4 只增表、stage/SENT 的 SQLite transaction 编排、duplicate callback 幂等及现有
context/checkpoint wire 主路径方向基本正确。Windows 与 WSL base 现有定向集合均通过；独立 fault injection
也证明 checkpoint CAS 写和最后 `mark_outbox_sent` 抛错时 transaction 会完整回滚。

但冻结的单账户 origin/scope、RecoveryRows context 外键闭包、固定 checkpoint key 与错误上下文脱敏仍有
可复现缺口，不能进入主验或标记 P0C 完成。

## 必须返工的问题

### P1：已有 checkpoint 未验证新 AccountSnapshot 的 genesis origin

- 现象：`ExecutionService.plan_and_stage` 在 checkpoint 已存在时只 decode state 并比较
  `state_id == row.identity`，没有比较 `state.origin_account_snapshot_id` 与本次已验证
  `account.snapshot_id`。同一 store 可继续 stage 第二个账户的 command/context，而 checkpoint 仍属于第一个账户。
- 根因：实现了“首次 genesis”与 wire identity，却漏掉设计 §4.2.2 的 existing checkpoint origin/scope 闭包。
- 独立最小复现：同一空 store 先以现金 2000 的 AccountSnapshot stage，再以现金 3000 的不同
  AccountSnapshot 和不同 target identity stage。探针输出：
  `first_origin=True, second_origin=False, second_commands=1, contexts=2`；第二次错误地成功。
- 应遵循规则：当前一个 execution store 只承载一个 PAPER/SHADOW 账户；已有 checkpoint 必须与本次 account
  origin/scope 完全闭合，不得继续写入第二账户，也不得覆盖 genesis。
- 新增测试：第二 AccountSnapshot 调用 `plan_and_stage` 必须返回稳定错误；counter、command、context、aggregate、
  outbox/delivery/stage 均无新增，原 checkpoint bytes/identity/tail 不变。重启后同样 fail closed。
- 通过条件：上述测试 Windows/WSL 均通过，错误无 cause/context 或敏感内容。

### P1：RecoveryRows 接受没有 command 父项的 orphan ledger context

- 现象：`read_recovery_rows` 对 event、aggregate、delivery 使用 LEFT JOIN 检查父项；`ledger_contexts` 却仅
  `SELECT command_id, identity, payload`，没有 join `commands`。离线关闭 foreign keys 并删除 command 后，
  recovery 返回 `commands=0, ledger_contexts=1`，没有 `ROW_CORRUPT`。
- 根因：migration 外键只保护正常在线写入，恢复读取没有按 §4.4 重证 command/context key 闭包。
- 独立最小复现：写 command + context，关闭 store；以 `PRAGMA foreign_keys=OFF` 删除 command；重开并调用
  `read_recovery_rows()`。实际输出 `0 1 cmd-a`。
- 应遵循规则：恢复快照必须 fail closed 验证 command、context 的 key/parent 闭包，不能把 SQLite 外键历史
  状态当作永久可信证据。
- 新增测试：仿照现有 event/aggregate/delivery broken-join 测试增加 context orphan；稳定返回
  `ROW_CORRUPT`，且 cause/context 均为空。
- 通过条件：RecoveryRows 不再返回 orphan context，正常排序与单事务快照测试保持通过。

### P1：LedgerAdapterError 仍可从隐藏 `__context__` 恢复 hostile payload

- 现象：`decode_ledger_context` 等边界在活动 `except` 内执行
  `raise LedgerAdapterError(...) from None`。`from None` 只抑制 traceback 展示，仍保留 `__context__`。
- 独立最小复现：`decode_ledger_context(b"TOKEN")`；捕获结果为
  `__context__=JSONDecodeError, __cause__=None, __suppress_context__=True`。JSONDecodeError 的 `doc` 仍持有
  hostile bytes 解码文本。service 的多处二次翻译也采用同一模式。
- 应遵循规则：设计 §4.4 要求不暴露 payload/token/traceback context；异常翻译必须离开活动 `except` 后再抛
  稳定错误，并断言 cause/context 都为空。
- 新增测试：parser、领域构造器、context provider、checkpoint wire 分别注入 `TOKEN`；对 adapter/service
  最终错误断言稳定 code、`__cause__ is None`、`__context__ is None`、展示抑制且对象图不可找回 TOKEN。
- 通过条件：所有公开边界满足上述断言，现有正常 wire/identity 回归不变。

### P1：checkpoint repository 接受任意调用者 key，破坏单 store canonical checkpoint

- 现象：设计 §4.1 冻结 `checkpoint_key` 为版本化固定常量，不接受调用者任意账户路径/表名；当前
  `put/get/replace_ledger_checkpoint` 只调用通用 `_require_key`。独立探针成功写入并恢复
  `arbitrary-account-path` checkpoint。
- 根因：固定 key 只在 service 私有常量中使用，没有在持久化边界或 schema 形成不变量。
- 新增测试：put/get/replace 的错误 key 以及数据库离线插入第二 key 后 recovery 均 fail closed；合法固定 key
  的 exact-idempotency/CAS 保持不变。
- 通过条件：API 与 RecoveryRows 均不接受第二 checkpoint 或任意 key，迁移后的空表仍为空。

### P2：checkpoint 与 outbox 最后一步失败缺少持久回归测试

- 现象：现有 service 测试只自动注入“第二个 ledger entry”失败；没有对
  `replace_ledger_checkpoint` 和最后 `mark_outbox_sent` 注入失败。
- 独立动态 fault injection 结果均正确：两种失败都返回 `CALLBACK_TRANSACTION_FAILED`，delivery 保持
  `LEASED`，checkpoint 与事务前相同，events/entries 均为 0。因此这是回归证据缺口，不是当前事务代码失败。
- 通过条件：把两种 fault injection 固化为测试，并逐项断言 event、aggregate、所有 entries、checkpoint 与
  SENT state 全部回滚；错误对象同样脱敏。

## 已通过的合同映射

- v004 migration 只创建 `ledger_contexts`、`ledger_checkpoints`；v3 upgrade 测试证明旧 command 保留且两张
  新表为空，没有伪造 context/checkpoint。
- stage 的 genesis、counter、command、context、aggregate、outbox/delivery、stage 均位于同一 store
  transaction；context provider 或最后 delivery 写失败会全回滚。
- SENT callback 的 event、aggregate、entries、checkpoint CAS、outbox SENT 位于同一 transaction；第二
  entry 失败的自动测试与 checkpoint/outbox 独立探针均证明回滚。
- duplicate callback 经 B5 applied-event/projection 语义成为零经济影响；NOT_SENT/UNKNOWN 不写 ledger entry。
- checkpoint tail 缺失、hostile identity、CAS conflict 与 legacy missing context 已有 fail-closed 测试。

这些通过项不能抵消上述 P1，特别是第二账户被接受和 orphan context 被 RecoveryRows 返回。

## 验证命令与结果

Windows 原生 `D:\Miniforge3\python.exe`，显式 `PYTHONPATH=src` 与独立 basetemp：

- 白名单 Ruff：`All checks passed!`
- 定向 mypy：`Success: no issues found in 5 source files`
- `test_execution_store.py test_execution_service.py`：`209 passed, 5 skipped`

WSL Miniforge base，DrvFS worktree：

- 同范围 Ruff：`All checks passed!`
- 同范围 mypy：`Success: no issues found in 5 source files`
- 同范围 pytest：`214 passed`

附加 Windows 只读式临时探针：

- 不同 account origin：失败复现，第二账户错误地成功 stage。
- orphan context：失败复现，RecoveryRows 返回无 parent context。
- hostile context error：失败复现，隐藏 `JSONDecodeError` 可达。
- 任意 checkpoint key：失败复现，repository 接受并恢复。
- checkpoint/outbox 最后一步异常：事务行为通过，两种均完整回滚。

本轮没有网络请求，没有提交，没有修改生产代码或实现测试；正式 G1/M3 数据、journal、候选与发布目录均未
接触。仅新增本独立初验报告；`src/quant/execution/__init__.py` 的既有 stat-only 状态保持不动。

## 最终判定

修复四项 P1、固化最后两步 rollback 测试并完成新一轮独立复验前，M4-P5-P0C 保持开放；不得据此关闭 P5、
M4 或任何正式 Gate。

---

## R1 独立复验（2026-08-02）

复验结论：**PASS**

本轮由未参与 R1 实现的独立 Agent 执行。只读核对原 FAIL 报告、R1 交付报告、
生产 diff 与实现者测试；未修改生产代码或实现者测试，未访问网络或正式数据。

### R1.1 原四个 P1 最小复现

| 原问题 | R1 独立复验 | 结果 |
|---|---|---|
| existing checkpoint 未绑定新 account origin | 同一 store 首先 stage 账户 A，再用不同 snapshot 的账户 B stage；稳定返回 `SERVICE_LEDGER_ACCOUNT_MISMATCH`。调用前后 `RecoveryRows`、daily counter 和 checkpoint 完全一致；关闭重开 store 后仍 fail closed | **PASS** |
| orphan ledger context 被 recovery 接受 | 正常写 command/context 后关闭 FK 并离线删除 parent command；`read_recovery_rows()` 稳定返回 `ROW_CORRUPT`，异常 `cause/context` 均为空 | **PASS** |
| hostile `TOKEN` 可从异常上下文找回 | parser、领域构造、context provider/stage 边界与 hostile checkpoint wire 均只返回稳定错误；`__cause__ is None`、`__context__ is None`、展示上下文抑制，`repr(error, args, vars)` 不含 `TOKEN` | **PASS** |
| repository 接受任意 checkpoint key | `put/get/replace` 对非 `paper-shadow-primary-v1` 全部返回 `LEDGER_CHECKPOINT_KEY_INVALID`；离线插入第二 key 后 recovery 返回 `ROW_CORRUPT`，不返回部分快照 | **PASS** |

canonical key 现由 `quant.execution.store.LEDGER_CHECKPOINT_KEY` 唯一导出；service 的 genesis、
callback CAS 和 recovery 均使用该同一常量。合法 key 的 exact-idempotency 与 stale-identity CAS
conflict 回归保持通过。

### R1.2 两项最终写入故障注入

`replace_ledger_checkpoint` 和最后 `mark_outbox_sent` 分别注入抛错，两个参数化
分支均返回 `CALLBACK_TRANSACTION_FAILED`：

- delivery 保持 `LEASED`，未转为 `SENT`；
- aggregate 与事务前字节相同；
- checkpoint identity/payload/tail 与事务前相同；
- event 和 ledger entry 均为空；
- 故障消息中的 `TOKEN` 不进入 `DispatchResult` 对象图。

两项事务回滚合同均 **PASS**。

### R1.3 独立验证证据

Windows 原生 `D:\Miniforge3\python.exe`，显式 `PYTHONPATH=<worktree>/src`：

```text
ruff check <P0C 生产与 store/service 测试白名单>
All checks passed!

mypy <5 个 P0C 生产文件>
Success: no issues found in 5 source files

pytest tests/unit/test_execution_store.py tests/unit/test_execution_service.py
216 passed, 5 skipped in 10.04s

pytest <四个 P1 复现 + 两项 fault injection 聚焦集>
10 passed in 3.80s
```

Windows 跳过项为既有 POSIX 文件系统语义。额外将两份测试文件也纳入 mypy
时，出现该测试文件既有的 Windows `sqlite3.connect` overload 和 `os.mkfifo` 平台 stub
错误；按任务/交付报告的五个生产文件口径重跑全绿，不将该既有测试类型问题
归因为 R1 回归。

WSL base R1 独立重跑请求在进程启动前被当前工具额度审查拒绝，未取得新的
Linux 结果。R1 交付报告也如实区分了 R1 前 WSL 基线，本复验不用该旧基线
冒充 R1 Linux Gate。

### R1.4 最终判定

原报告四项 P1 缺口已按原通过条件关闭，两项 P2 事务 fault injection 已固化且
通过。本轮允许 M4-P5-P0C 进入主 Agent 最终验收。本 **PASS** 不等于 P5、M4
或任何正式 Gate 已关闭；WSL/Linux 最终证据仍由主 Agent 按门禁需求补齐。
