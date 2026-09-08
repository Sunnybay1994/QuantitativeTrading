# M4 P4-C/P4-R 精确派发与 Durable Cancel 主 Agent 最终验收报告

日期：2026-08-11  
结论：PASS

## 验收结论

P4-R 确认范围内 exact allowlist 派发与 P4-C durable cancel 的工程子合同通过主验。派发保持全有或全无；撤单
保持持久化 intent、lease/attempt fencing、late-fill crossing 前复核、callback/OMS link/terminal state 同事务，以及
NOT_SENT 可重试、UNKNOWN 需人工查询的边界。本结论不关闭完整 P4、P6、P8、M4 或 PAPER soak Gate。

## 外部独立初验

- P4-R：PASS；Windows `230 passed, 5 skipped`，并完成 SQLite 竞态、漂移、双连接抢占和递归异常脱敏对抗。
- P4-C R2：PASS；Windows `341 passed, 5 skipped`，覆盖 arm 后 late fill、跨 lease、SENT callback link 缺失、
  NOT_SENT 审计码与 callback 事务失败。

## 主 Agent 复核

- 高风险定向节点：`10 passed`。
- 覆盖 exact selected allowlist、unclaimable member 全体拒绝、cancel callback/OMS link/terminal state 同事务、
  started 后跨 lease、arm 后 late fill、callback 事务失败与双 callback 缺 link 的恢复分类。
- 与已主验的 P4-R2 全局 PENDING exact 集合闭包组合后，未发现确认范围被扩大或并发新增命令被静默派发。

## 剩余边界

证据仍属于工程工作树与 DrvFS 开发兼容；formal account、formal store/gateway/service/runner、ext4 与真实
28 日 soak 尚未完成。

