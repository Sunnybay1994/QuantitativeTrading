# M4 P8 RUN-0B2A2：P7 Durable Risk Exact Completeness 主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（仅 development 工程合同）**

## 1. 验收结论

B2A2 已把 P7 风控来源唯一收缩到 `RecoveryResult.risk_receipts`。公开报告 builder 不再接收调用方
`risk_decisions`；fresh recovery、B2A1 公共语义 verifier、ORDER-only 风控行投影，以及 P8 session/fault
retained recovery v2 wire 已形成同一条 exact completeness 闭包。实现、自测和全新独立初验均已通过，
本轮主验未发现新的合同缺口。

本结论不代表正式 PAPER runner、scheduler、真实 28 日 soak、WSL2/ext4 或 M4 Gate 通过；M4 状态继续为
`WAITING_FOR_SOAK_EVIDENCE`。

## 2. 主验核对

- `build_execution_report` 的公开签名只有 `recovery`、`reconciliation`、`as_of`，无旧参数兼容入口。
- `_verify_recovery` 要求 exact `RecoveryResult`，fresh 构造时透传全部 `risk_receipts`。
- 生成 totals/report identity 前再次调用 B2A1 唯一公共 `verify_risk_receipt_semantic_closure`。
- 只有 durable ORDER receipt 投影为既有 `ExecutionRiskLine`；CANCEL receipt 参与闭包但不伪装 pre-trade rule。
- P8 session/fault retained facts 使用显式 v2 schema，exact 保留公共 canonical risk receipt wire；无 v1 空 receipt 回填旁路。
- hostile 下游异常在公开边界稳定脱敏，且报告路径保持零网络、零 SQLite、零墙钟读取。

独立复验另补递归 hostile exception graph 与合法不同 closure 整体替换反例，均按冻结边界 fail closed；详见
`M4_P8_RUN0B2A2_P7DurableRiskExactCompleteness独立复验报告.md`。

## 3. 验证证据

实现与独立初验完整定向组：

- Windows：`89 passed, 1 skipped`；Ruff、mypy 通过；
- WSL base：`90 passed`；Ruff、mypy 通过；
- WSL 目标位于 DrvFS，不作为 ext4 Gate 证据。

主 Agent 定向复核：

- durable risk 投影、旧 caller risk 拒绝、hostile verifier 脱敏、P8 retained receipt exact wire、whole-rehash
  anchor 拒绝共 5 个测试节点（含参数化）→ `10 passed`；
- 白名单四文件 Ruff → `All checks passed`；
- 两个生产文件 mypy → `Success: no issues found in 2 source files`。

首次主验 pytest 未设置本 worktree 的 `PYTHONPATH=src`，在 collection 阶段导入了错误源码树并报
`ModuleNotFoundError`；补齐冻结环境后同一组立即通过。该次结果是命令环境错误，不计为产品失败。

## 4. 保留边界

- 未创建或修改 formal root、journal、runner、scheduler、broker/runtime 状态；未联网、未 add/commit。
- B2A1/B2A2 证明 durable recovery 与报告 exact closure，不把拥有全部 SQLite/evidence/anchor 写权限的攻击者
  描述成已被密码学阻止。
- 后续仍需正式 policy/config、market/target/account loader、生产装配、WSL2/ext4 路径和真实 28 日证据。
