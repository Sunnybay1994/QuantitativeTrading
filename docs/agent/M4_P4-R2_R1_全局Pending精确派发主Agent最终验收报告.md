# M4 P4-R2 R1 全局 PENDING 精确派发主 Agent 最终验收报告

日期：2026-08-11  
结论：PASS

## 验收结论

全局可派发 PENDING 集合与操作者已确认集合的 exact 绑定、claim/attempt fencing、写失败分类、CLI
`CONFIRMATION_DRIFT` 映射及异常脱敏均符合冻结任务。该结论只关闭 P4-R2 子合同，不关闭 P4、M4、Linux/ext4
或真实 PAPER Gate。

## 独立初验证据

未参与实现的外部 Agent 结论为 PASS：Windows `276 passed, 5 skipped`，WSL base/DrvFS `281 passed`；
Ruff、mypy 及 32 组新增对抗均通过。对抗覆盖跨账户/会话集合、lease/attempt fencing、NOT_SENT 与 UNKNOWN、
submit/cancel 混合、少/多/重复/乱序、hostile 递归异常图与冷导入零副作用。

## 主 Agent 复核

- 高风险定向节点：`6 passed`。
- 覆盖完整全局集合派发、并发新增拒绝、同集合唯一获胜、writer busy/claim failure 分类、提交与撤单确认漂移。
- 复核外部报告、任务边界及工作树差异，未发现越权扩展。

## 剩余边界

WSL 证据来自 DrvFS，不是 ext4；本包不包含正式 PAPER 账户、formal store/gateway/service/runner 或 28 日 soak。

