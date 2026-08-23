# M4-P2A Gateway Dispatch 结果边界合同主 Agent 最终验收报告

日期：2026-07-22  
结论：**P2A 合同子包通过主验**；不宣布 P2、P4 或 M4 Gate。

## 1. 职责闭环

- 任务：[`M4_P2A_GatewayDispatch结果边界合同任务单.md`](M4_P2A_GatewayDispatch结果边界合同任务单.md)
- 主 Agent 预验：[`M4_P2A_GatewayDispatch结果边界合同主Agent预验收报告.md`](M4_P2A_GatewayDispatch结果边界合同主Agent预验收报告.md)
- 未参与实现的外部初验：
  [`M4_P2A_GatewayDispatch结果边界合同外部独立初验报告.md`](M4_P2A_GatewayDispatch结果边界合同外部独立初验报告.md)

外部初验保持生产代码与实现者测试只读，只写自己的报告，并增加 int 子类 attempt、duck-typed result、
相等时间边界和脱敏等实现者未使用反例。

## 2. 主验结论

- `DispatchCertainty` 精确为 `NOT_SENT/SENT/UNKNOWN`，transport result 与 callback 闭包 fail closed；
- command、attempt、PAPER mode、UTC、identity 均在 adapter 前验证，非法输入调用次数为零；
- result command/attempt fencing 与 callback command/identity/time 校验成立；完全相同事件保持原顺序，
  同 id 异 payload 被拒绝；
- 合同错误使用稳定脱敏 code，不泄露 command/broker/symbol/hostile timezone 内容，cause/context 为空；
- gateway 合同模块不依赖 store/OMS，未引入真实 IO 或生产 fake。

`CALLBACK_CONFLICT` 在当前完整 event identity 下较难单独到达，但同 id 异 payload 会更早由
`GATEWAY_CALLBACK_INVALID` 拒绝，满足冻结的 fail-closed 结果语义，不构成阻塞。

## 3. 验证证据

主 Agent 预验与外部独立初验均执行双平台定向验证：

```text
WSL Miniforge base pytest → 17 passed
Windows Miniforge pytest → 17 passed
Ruff → All checks passed
mypy --no-incremental → Success: no issues found in 2 source files
```

## 4. 剩余边界

本子包只关闭 Gateway dispatch 的结果边界合同。PaperGateway adapter、outbox service、OMS/store 映射、
对账恢复、真实 PAPER 运行和四周稳定性仍属于后续 P2/P4/P5/P6-P8 工作，不得据此标记 M4 完成。
