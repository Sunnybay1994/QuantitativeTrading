# M4 P4-P1 与执行服务主 Agent 最终验收报告

日期：2026-08-11  
结论：PASS

## 验收结论

执行状态持久化前置与同步可恢复执行服务的工程合同通过主验。事务原子性、CAS/SAVEPOINT、delivery
attempt/lease fencing、callback/event/aggregate/outbox 同提交、NOT_SENT/UNKNOWN、重放幂等与 writer busy 分类符合冻结
边界。该结论不关闭完整 P4、formal PAPER 装配、Linux/ext4 或 M4 Gate。

## 外部独立初验

全新外部只读会话结论 PASS：Windows `265 passed, 5 skipped`，WSL base/DrvFS `270 passed`；Ruff、mypy
通过。新增对抗覆盖递归异常脱敏、COMMIT 失败零半写入、双 worker 旧 attempt fencing、callback 中途回滚、
TX_BUSY 稳定映射与零网络 I/O。后续 P4-R/P4-C/P4-R2/P5 合同未掩盖基础 durable 缺陷。

## 主 Agent 复核

- 高风险定向节点：`9 passed`。
- 覆盖 aggregate strict CAS/exact replay、外层事务整体回滚、过期 lease 后旧 attempt 拒绝、双连接 writer busy、
  SENT callbacks/aggregate 同事务、callback/final-write 回滚与双 worker lease fencing。
- 已结合 P4-R、P4-C、P4-R2、P5 的独立复验及主验结果复核相邻闭包。

## 已知边界

通过 `quant.backtest.__init__` 的宽包导入仍会加载 `httpx`/Tushare connector；本包已证明零网络 I/O，但不把它
表述成最小依赖冷导入闭包。WSL 证据来自 DrvFS，不是 ext4。

