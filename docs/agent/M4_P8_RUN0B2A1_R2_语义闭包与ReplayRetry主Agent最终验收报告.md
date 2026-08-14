# M4 P8 RUN-0B2A1 R2：语义闭包与 Replay Retry 主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（development 工程合同）**

## 1. 验收范围

本次只验收 durable ORDER/CANCEL risk transition receipt、同 OMS 事务写入、recovery exact closure、exact
replay 与可重试事务失败边界。P7 caller risk 移除属于后续 B2A2；正式 PAPER runtime、scheduler、真实 soak、
WSL2/ext4 与 M4 Gate 均不在本结论内。

权威任务与证据：

- `M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery任务单.md`；
- `M4_P8_RUN0B2A1_R2_语义闭包与ReplayRetry交付报告.md`；
- `M4_P8_RUN0B2A1_R2_语义闭包与ReplayRetry独立复验报告.md`。

## 2. 主验结论

R1 三项阻断均已闭合：

1. `RecoveryResult` 与 `recover_local_state` 共用 public semantic closure，receipt 缺失、增加、重复 owner、
   cross-plan/cross-kind、换序或 outer identity 全量重算仍会拒绝；
2. ORDER/CANCEL exact replay 同时绑定 expected counter key、完整 retained global/per-key chain 与当前 counter
   tail；合法 target 后存在后续 transition 的 non-tail replay 保持幂等，错误 scope 与 tail drift 拒绝；
3. 原生 SQLite writer lock 的 `TX_BUSY` 保持 StoreError 可重试语义，零部分写；释放锁后 fresh retry 成功。

代码复核确认：

- receipt canonical codec 与 `verify_risk_receipt_semantic_closure` 是共同 ownership verifier；
- recovery 还逐项核对 stored row、global predecessor、per-key counter predecessor/projected payload 与最终
  counter row；
- service replay 在返回既有结果前 fresh 读取 commands/cancels/receipts，调用同一 verifier，并核对目标 key
  的当前 counter tail；
- `stage_cancel` 对 `ExecutionServiceError`、`StoreError` 分别保留原边界，未知错误才映射固定失败码。

诚实信任边界保持不变：拥有整个 OMS root 离线写权限者若协调替换一套语义合法的 SQLite closure 并重算所有
自哈希，B2A1 自身不提供外部数字签名证明。最终 P8 independent anchor 承担首次 retained closure 绑定；本包未
把自哈希链误报为不可伪造来源证明。

## 3. 验证证据

实现与独立复验的完整定向组：

- Windows：`295 passed, 5 skipped`；Ruff PASS；mypy 5 files PASS；
- WSL base：`300 passed`；Ruff/mypy PASS；`findmnt` 为 DrvFS，非 ext4 Gate；
- 独立新增：ORDER→CANCEL→ORDER non-tail replay、receipt middle missing/swap/duplicate owner/cross-kind、
  hostile nested exception graph，以及第三 SQLite connection `BEGIN IMMEDIATE` 写锁与解锁后重试，均 PASS。

主 Agent 复核：

- Windows 核心五类节点（参数化后 9 cases）：`9 passed in 3.49s`；
- Ruff：5 个 B2A1 生产文件 `All checks passed`；
- mypy：同 5 个生产文件 `Success: no issues found`；
- 定向 `git diff --check` 通过，仅有既有 LF/CRLF 提示。

主验第一次输入了一个已更名的 pytest node，pytest 明确报告 node not found；该命令未形成验收证据。随后以
实际节点名重跑上述 9 cases 并通过，静态检查亦独立通过。

## 4. 状态与下一步

B2A1 R2 development 工程合同正式通过，解锁
`M4_P8_RUN0B2A2_P7DurableRiskExactCompleteness任务单.md`。B2A2 将删除 P7 的 caller
`risk_decisions` 参数，唯一消费 recovery 内 durable receipts，并同步 P8 retained recovery wire。

本结论不改变 `WAITING_FOR_SOAK_EVIDENCE`，不创建 formal root，不注册/启动任务，也不宣称 M4 或 Linux/ext4
Gate 通过。
