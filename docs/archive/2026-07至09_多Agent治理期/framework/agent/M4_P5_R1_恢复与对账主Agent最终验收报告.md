# M4 P5 R1 恢复与对账主 Agent 最终验收报告

日期：2026-08-11  
结论：PASS

## 验收结论

P5-P0A 原子恢复快照、P5-P0B canonical wire、P5-P0C ledger 持久化事务闭包以及 P5-R1 本地恢复与 PAPER
对账的工程合同通过主验。原子读取、canonical 编解码、checkpoint/CAS、回调事务、恢复闭包、差异分类与只读
对账保持一致。本结论不关闭完整 P5、M4、Linux/ext4 或真实 PAPER Gate。

## 外部独立初验证据

- P0A：Windows `206 passed, 5 skipped`，WSL base `211 passed`；新增原子快照对抗通过。
- P0B：Windows/WSL 各 `73 passed`；Ruff、mypy 通过。
- P0C：返工后 Windows `216 passed, 5 skipped`，附加对抗 `10 passed`；独立结论 PASS。
- P5-R1：返工后独立结论 PASS，允许进入主验。

所有 WSL 结果均为 DrvFS 开发兼容证据，不冒充 ext4 Gate。

## 主 Agent 复核

- 高风险定向节点：`15 passed`。
- 覆盖单事务恢复快照、broken join fail-closed、SQLite hostile 异常脱敏、checkpoint CAS、stage 缺 ledger context
  全事务回滚、adapter/checkpoint hostile payload、合法重签后的语义漂移拒绝，以及并发 writer 下的一致快照。
- Ruff：PASS。
- mypy（三个生产模块）：PASS。
- cold import：PASS，未加载 Qlib、LightGBM、MLflow。
- scoped `git diff --check`：PASS；仅出现既有 LF/CRLF 提示。

## 剩余边界

正式账户配置与 capability、formal durable store/gateway/service/runner、真实 broker snapshot 入口、Linux ext4 验证及
28 日 PAPER soak 仍未完成；这些事项不得由本报告推导为 M4 通过。

