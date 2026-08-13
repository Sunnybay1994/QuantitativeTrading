# M4-P5-P0C Ledger 持久化事务闭包交付报告

日期：2026-08-02  
状态：独立初验返工与 Windows 自测完成，待独立复验  
任务单：[`M4_P5-P0C_Ledger持久化事务闭包任务单.md`](M4_P5-P0C_Ledger持久化事务闭包任务单.md)  
权威设计：[`M4_P5-P0恢复与账本持久化前置设计.md`](M4_P5-P0恢复与账本持久化前置设计.md) §4

## 交付摘要

- schema 升至 v4，新增 immutable `ledger_contexts` 与单 store canonical
  `ledger_checkpoints`，checkpoint 显式闭合 `last_entry_id`。
- 扩展唯一恢复快照 `RecoveryRows`，在同一只读事务中读取 context、checkpoint， hostile identity、缺失
  entry tail 或旧 opaque wire 均 fail closed。
- 新增 typed pure ledger adapter，只编排既有 B5 `build_ledger_state` / `apply_execution_event` 与公共 wire；
  未复制结算、FX、现金、持仓或 entry 计算。
- `plan_and_stage` 在 command/outbox/delivery 同一事务写 immutable context，并按首次 store 使用建立 genesis
  checkpoint；任何 context/rule/FX/genesis 失败均回滚。
- SENT callback 在同一事务写 event、OMS aggregate、append-only ledger entries、checkpoint CAS 与 delivery
  SENT。NOT_SENT/UNKNOWN 不产生 ledger 经济影响。
- v3 仅做增表迁移，不为历史 command 伪造 context；旧 pending row 在 typed 使用边界因缺 context/checkpoint
  明确失败。

## 主要反例证据

- stage 缺 ledger context 全事务回滚；legacy staged command 缺 context fail closed。
- callback 第二个 ledger entry 写失败时，event、aggregate、entries、checkpoint 与 SENT 状态全部回滚。
- duplicate callback 不产生重复 entry；使用同一 persisted context/checkpoint 重放得到同一 state identity。
- checkpoint exact-bytes 幂等、异 bytes/CAS 冲突；hostile context/checkpoint identity 在恢复时失败。
- checkpoint 引用的 entry tail 被离线破坏后，恢复快照因 join 不闭合而 fail closed。
- NOT_SENT/UNKNOWN 不写 ledger entry；v3 升级保留历史 command 且新表为空。

## 验证结果

Windows 原生 Miniforge：

- 白名单 Ruff：通过。
- 定向 mypy（5 个生产/服务测试文件）：`Success: no issues found in 5 source files`。
- `tests/unit/test_execution_store.py tests/unit/test_execution_service.py`：
  `209 passed, 5 skipped in 12.78s`。跳过项为 Windows 平台不具备的 POSIX 文件语义。

WSL Miniforge `base`（同一隔离 worktree）：

- 白名单 Ruff：通过。
- 定向 mypy：`Success: no issues found in 5 source files`。
- 同一组 pytest：`214 passed in 9.61s`。

验证均设置 `PYTHONPATH=src`，pytest 禁用 cache provider 并使用系统临时目录，未写正式 G1/M3 数据、journal
或候选目录。

## 范围与剩余风险

- 本交付仅关闭 P0C 的 schema/context/checkpoint/SENT 原子恢复前置，不宣称 M4-P5、M4 或正式 G1 Gate
  已通过。
- 未运行全量回归；后续独立初验应补充未知 hostile row、进程重启恢复和跨模块恢复编排反例。
- 当前 worktree 原有 `src/quant/execution/__init__.py` 无关脏改保持原样，本任务未修改或纳入交付。
- Windows 与 `/mnt/f` DrvFS 验证属于双平台开发合同反馈，仍不替代要求 ext4 的平台特有正式 Gate。

## R1 独立初验返工

依据：[`M4_P5-P0C_Ledger持久化事务闭包独立初验报告.md`](M4_P5-P0C_Ledger持久化事务闭包独立初验报告.md)。

- existing checkpoint 现在同时验证 wire identity 与 `origin_account_snapshot_id == account.snapshot_id`；同一
  store 的第二账户在 counter/command/context/aggregate/outbox/stage 写入前 fail closed，事务前后恢复快照、
  counter 和 checkpoint 完全不变，重启后规则相同。
- `RecoveryRows.ledger_contexts` 改为 LEFT JOIN parent command 并验证 join key；离线关闭 FK 删除 command
  后稳定返回 `ROW_CORRUPT`。
- adapter 及 P0C service 翻译边界离开 active `except` 后再抛稳定错误；parser、领域构造、context provider、
  hostile checkpoint wire 测试均断言 `__cause__` / `__context__` 为空，错误对象不包含 `TOKEN`。
- repository 导出唯一 `LEDGER_CHECKPOINT_KEY`；put/get/replace API 只接受该 key，RecoveryRows 拒绝离线
  插入的第二 key。
- 新增 checkpoint CAS 写失败和最终 `mark_outbox_sent` 失败故障注入；两者均证明 event、aggregate、entries、
  checkpoint、delivery SENT 在同一事务回滚。

R1 Windows 结果：

- 白名单 Ruff：通过。
- 定向 mypy：`Success: no issues found in 5 source files`。
- store/service 定向 pytest：`216 passed, 5 skipped in 12.68s`。
- `git diff --check`：通过。

此前记录的 WSL `214 passed` 是 R1 前基线。本次 R1 的 WSL base 重跑因当前执行额度审查在进程启动前被
拦截，故不把旧结果表述为 R1 Linux 通过；待独立复验补跑。独立初验报告保持只读，未修改。
