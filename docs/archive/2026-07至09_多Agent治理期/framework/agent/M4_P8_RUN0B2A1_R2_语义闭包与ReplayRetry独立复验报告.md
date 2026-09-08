# M4-P8-RUN-0B2A1 R2 语义闭包与 Replay/Retry 独立复验报告

状态：**PASS，可进入主 Agent 最终验收**  
日期：2026-08-09  
角色：未参与 R2 实现的全新独立只读复验  
权威合同：[`M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery任务单.md`](M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery任务单.md) §12  
R1 失败证据：[`M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery独立复验报告.md`](M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery独立复验报告.md)  
R2 交付：[`M4_P8_RUN0B2A1_R2_语义闭包与ReplayRetry交付报告.md`](M4_P8_RUN0B2A1_R2_语义闭包与ReplayRetry交付报告.md)

## 1. 结论

R1 的三个阻断均已闭环：

1. `RecoveryResult` 现在调用无 IO 的共享 semantic verifier，完成 receipt 自链、per-key
   counter 链以及 ORDER/CANCEL 与 retained commands/cancels 的 exact-once 所有权闭包；
2. ORDER/CANCEL exact replay 在返回 `replayed=True` 前 fresh 验证 expected counter key、完整
   global/per-key receipt chain 和当前 counter tail；合法的旧 target 不被错误要求为 tail；
3. `stage_cancel()` 不再吞掉 `StoreError("TX_BUSY")`，order/cancel 在真实独立 SQLite writer
   lock 下均保留可重试稳定码，锁内零部分写，释放后 fresh retry 成功。

本轮没有发现新的 B2A1 阻断。可由主 Agent 复核后解锁 B2A2；本结论仍只是
development 工程合同，不代表正式 RUN-0B2、WSL2/ext4 或 28 天 soak Gate 通过。

## 2. 合同与代码核对

- `verify_risk_receipt_semantic_closure()` 对全局 sequence/previous、per-key predecessor/projected、
  canonical round-trip、ORDER plan/intent/command 有序归属、CANCEL target command 与 exact-once owner
  同时 fail closed；空本地事实不接受非空 receipt。
- `RecoveryResult.__post_init__()` 通过 `_valid_recovery_receipts()` 调用同一 verifier，并在所有
  retained 字段上重算 outer `recovery_id`；不再仅依赖 `recover_local_state()` 的调用顺序。
- `_verify_replay_risk_chain()` 在当前事务 snapshot 中读全部 commands/cancels/receipts，并把
  expected key 的最后 projected counter 与当前 durable counter row exact 比较。
- `_require_order_receipt()` 与 `_require_cancel_receipt()` 都显式绑定 expected key；目标 receipt
  可以位于合法后续 transition 之前，但必须属于完整有效链。
- `stage_cancel()` 对 `ExecutionServiceError` 与 `StoreError` 分别原语义传播；只有其他未知异常
  才脱敏为 `CANCEL_STAGE_FAILED`。
- R2 未改 P7/soak/CLI/broker/runtime/formal root；工作树中的大量既有脏文件与本复验
  无关，本轮不修改、不清理、不 add/commit。

## 3. 独立对抗反例

除实现者回归外，本复验另行构造了两组未写入仓库的独立探针：

1. 在真实 `ORDER R1 → CANCEL C1 → ORDER R2` 同 key 链上，R1 与 C1 都能在成为
   non-tail 后 exact replay；对 `RecoveryResult` 的 receipt tuple 做 missing-middle、swap-first-last、
   duplicate-receipt、duplicate-owner 和 canonical cross-kind owner 替换，每次都完整重算
   outer `recovery_id`，全部稳定拒绝为 `RECOVERY_RESULT_INVALID`。
2. 用原生 `sqlite3` 第三连接持有 `BEGIN IMMEDIATE`，而非复用 store 的 transaction helper。
   ORDER 与 CANCEL direct service 都返回 detached `TX_BUSY`；持锁连接前后统计证明
   counter/command/cancel/delivery/receipt 零部分写；释放锁后 fresh retry 生成唯一合法后继。

hostile verifier 还被注入了带嵌套 cause 的 path/SQL/TOKEN marker；公开异常图只保留固定
`RECOVERY_RESULT_INVALID`，`cause/context` 为 `None`，marker 不可见。

## 4. 诚实信任边界

独立探针将整条合法 ORDER/CANCEL/ORDER closure 协调重签到新 counter scope，并重算每条
inner receipt 与 outer `recovery_id`；低层 `RecoveryResult` 仍可构造。这与任务单明示的边界一致：
B2A1 只证明同库的结构、counter 和 exact ownership 闭包，不抵御攻击者对整套合法 SQLite
closure 协调替换。本报告不将该预期结果误判为缺陷，也不声称本包提供来源防伪；
后续由独立 P8 evidence/anchor 绑定首次观察。

## 5. 可重现验证

Windows 原生 `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

- `pytest tests/unit/test_risk_wire.py tests/unit/test_execution_store.py tests/unit/test_execution_service.py tests/unit/test_reconcile.py -q`
  → **295 passed, 5 skipped**；
- 白名单 Ruff → **All checks passed**；
- 白名单生产 mypy → **Success: no issues found in 5 source files**；
- 独立 semantic/non-tail/hostile/whole-rehash 探针 → **PASS**；
- 独立 raw SQLite writer-lock/retry 探针 → **PASS**。

WSL Miniforge base，`/mnt/f/.../m3-g8ab-prereq`：

- 同组定向 pytest → **300 passed**；
- 同组 Ruff → **All checks passed**；
- 同组生产 mypy → **Success: no issues found in 5 source files**；
- `findmnt -T /mnt/f` → `drvfs rw,noatime,uid=1000,gid=1000,case=off`。

WSL 证据是 DrvFS 上的跨平台工程回归，**不是 WSL2/ext4 Gate**。RUN-0B2 生产装配、
P7 exact completeness、正式 runner/scheduler 和 28 天 soak 仍待后续，M4 继续为
`WAITING_FOR_SOAK_EVIDENCE`。
