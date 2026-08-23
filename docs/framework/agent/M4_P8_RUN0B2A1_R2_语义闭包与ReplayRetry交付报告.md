# M4-P8-RUN-0B2A1 R2 语义闭包与 Replay/Retry 交付报告

状态：R2 返工与自测完成，待另一全新独立上下文复验；本报告不宣布 Gate 通过。  
日期：2026-08-09  
冻结合同：[`M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery任务单.md`](M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery任务单.md) §12  
R1 复验：[`M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery独立复验报告.md`](M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery独立复验报告.md)

## 1. F1：RecoveryResult retained semantic closure

- 在 `risk_wire` 增加无 IO 的共同 semantic closure verifier，同时由 `RecoveryResult.__post_init__` 与
  `recover_local_state()` 调用。
- verifier fresh 重验 canonical/global sequence、previous chain、per-key predecessor/projected chain；每个 retained
  command 必须恰有一条 ORDER receipt owner，plan/intent/command 顺序 exact；每个 retained cancel 必须恰有一条
  CANCEL owner，并 exact 指向 retained target command。
- 空 commands/cancels 只接受空 receipts；缺失、额外、重复 owner、cross-plan、cross-kind 即使重编码全部 receipts
  并重新计算 outer `recovery_id`，仍稳定 `RECOVERY_RESULT_INVALID`。
- store-only final counter row 与 cancel policy metadata 仍由 `recover_local_state()` 的外层 retained-row 验证完成；
  公共构造器没有这些行时不伪造证明。

## 2. F2：ORDER/CANCEL replay scope 与 retained chain

- `plan_and_stage()` 在 existing-stage 分支前即派生
  `risk_counter_scope:session_date` expected key；ORDER replay 显式绑定 expected key。
- ORDER/CANCEL replay 都从当前事务 snapshot 读取完整 receipt/command/cancel closure，使用共同 verifier fresh 验证
  global/per-key chain，再验证 expected key 的当前 daily counter row等于该 key 最后 projected counter。
- target receipt 只须在完整合法链中，不要求是全局或 per-key tail；测试覆盖
  `ORDER R1 → CANCEL C1 → ORDER R2` 后 R1 与 C1 均可 exact replay。
- ORDER/CANCEL receipt 即使 whole-rehash 到错误 scope 并同步更新 indexed metadata/payload，也在返回 replay 前拒绝；
  current counter tail 漂移、断链或 legacy 缺 receipt 同样 fail closed。

## 3. F3：retryable transaction boundary

- `stage_cancel()` 不再用宽异常翻译吞掉 `StoreError`；store transaction/busy/CAS 类稳定码按与 ORDER 相同的层边界
  原样传播，未知非 store 异常仍映射 `CANCEL_STAGE_FAILED`。
- 真实两个 SQLite connection 的 writer-lock 测试覆盖 ORDER 与 CANCEL direct service：竞争者得到 `TX_BUSY`，
  cause/context 为空；持锁 snapshot 证明零新增 counter/command/cancel/receipt；释放后 fresh retry 使用当前 tail 成功，
  不分叉、不丢 counter。

## 4. 新增/强化反例

- `RecoveryResult` missing、extra empty ORDER、duplicate command owner、cross-plan owner、extra CANCEL，全部协调重算
  inner receipt 与 outer identity 后仍拒绝。
- ORDER/CANCEL wrong counter scope whole-rehash replay。
- ORDER current counter tail 离线漂移 replay。
- mixed chain 中非 tail ORDER/CANCEL exact replay。
- ORDER/CANCEL 两连接真实 `TX_BUSY`、锁内零部分写与释放后 fresh retry。
- 原 R1 canonical、rollback、legacy、三类 store serialization 与 recovery tamper 回归全部保留。

## 5. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

- 四文件定向 pytest → **295 passed, 5 skipped**；
- 白名单 Ruff → **All checks passed**；
- 白名单生产 mypy（5 个 source files）→ **Success: no issues found**。

WSL Miniforge base，`/mnt/f/.../m3-g8ab-prereq`：

- 同组 pytest → **300 passed**；
- 同组 Ruff → **All checks passed**；
- 同组生产 mypy（5 个 source files）→ **Success: no issues found**；
- `findmnt -T /mnt/f` → `drvfs rw,noatime,...`，仅为 WSL/DrvFS 工程证据，**不是 WSL2/ext4 Gate**。

## 6. 边界与后续

- 未修改 P7/reporting、soak、CLI/runner、broker/runtime、formal root 或正式 journal；未联网、未 add/commit。
- R1 已记录的 P7 retained-copy 尚未携带 `risk_receipts`，仍属于 B2A2，R2 没有越界处理。
- 同库完整合法 closure 协调替换并重算全部自哈希仍在本包明示信任边界之外，后续由独立 P8 evidence/anchor
  绑定首次观察；R2 不宣称来源不可伪造。
- 需由未参与 R2 实现的另一全新上下文独立复验；在复验与主 Agent 终验前 B2A2 不解锁，M4 仍为
  `WAITING_FOR_SOAK_EVIDENCE`。
