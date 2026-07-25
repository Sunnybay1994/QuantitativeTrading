# M4-P2A Gateway Dispatch 结果边界合同主 Agent 预验收报告

## 结论

实现与本地双平台定向证据满足冻结合同；状态为 **PRELIMINARY PASS / 外部独立初验待完成**。本报告不替代
项目要求的全新外部 Cursor 独立初验，也不关闭 P2、P4 或 M4 Gate。

## 合同映射

- `DispatchCertainty` 明确区分 `NOT_SENT/SENT/UNKNOWN`；非 `SENT` 结果禁止 callback。
- `GatewayDispatchResult` 为冻结值对象，`dispatch_attempt` 只接受正真 `int`，callbacks 只接受 tuple。
- `validate_gateway_submit` 在 adapter 前重验 command/intent identity、PAPER、attempt 和 aware UTC。
- `verify_gateway_dispatch_result` 重验 command/attempt fencing、callback identity/归属/时间与冲突；保持观察顺序
  和相同 payload 重复，不排序、不去重。
- `GatewayContractError` 使用稳定脱敏 code，并清除异常 cause/context。

实现者测试覆盖冻结反例，并额外覆盖 hostile `tzinfo` 与通过 `object.__setattr__` 篡改 frozen result 后的重验。

## 2026-07-22 验证

- WSL Miniforge base：`17 passed`；Ruff 全通过。
- WSL mypy 2.2.0：repo 内 SQLite cache 在 DrvFS 报 `sqlite3.OperationalError: disk I/O error`；改用
  `--no-incremental --cache-dir /tmp/quant-mypy-p2a` 后 `Success: no issues found in 2 source files`。
- Windows 原生 Miniforge + PowerShell 7：`17 passed`；Ruff 全通过；mypy `--no-incremental` 通过。

## 外部初验阻塞

主 Agent 按任务要求启动全新的 `cursor-grok-4.5-high` 只读初验会话，只允许写唯一外部报告；宿主租户
策略在进程创建前拒绝了该调用。外部会话没有启动、没有修改生产代码/测试/报告。为保持职责分离，不以
主 Agent 或内部 subagent 顶替。

解除阻塞后的通过条件：外部初验逐项映射任务书、运行双平台定向命令，并增加至少一个实现者未使用的
对抗性反例；若发现问题，回到“外部实现返工 → 另一外部会话复验”闭环。
