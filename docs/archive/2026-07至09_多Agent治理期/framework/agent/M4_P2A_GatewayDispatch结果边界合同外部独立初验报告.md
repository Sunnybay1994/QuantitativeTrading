# M4-P2A Gateway Dispatch 结果边界合同外部独立初验报告

- 角色：未参与实现的全新外部独立初验 Agent（只读生产代码与实现者测试）
- 日期：2026-07-22
- 合同：[`M4_P2A_GatewayDispatch结果边界合同任务单.md`](M4_P2A_GatewayDispatch结果边界合同任务单.md)
- 预验：[`M4_P2A_GatewayDispatch结果边界合同主Agent预验收报告.md`](M4_P2A_GatewayDispatch结果边界合同主Agent预验收报告.md)
- 结论：**EXTERNAL PRELIMINARY PASS**（初验通过，可进入主 Agent 终验）
- 明确非结论：不宣布 P2/P4/M4 Gate 通过；不替代主验

## 1. 范围与只读约束

已读：根 `AGENTS.md`、`.ai/README.md`、`.ai/coding_rules.md`、任务单、预验报告、
`src/quant/execution/gateways/{__init__,contracts}.py`、`tests/unit/test_gateway_transport_contracts.py`。

本会话仅写入本报告；未改生产代码、未改实现者测试、未新增依赖。

## 2. 合同逐项映射

| 成功标准 | 证据 | 判定 |
|---|---|---|
| forged command/intent 在 adapter 前拒绝；SHADOW call count=0 | `validate_gateway_submit` 先 identity/PAPER/attempt/UTC；`test_shadow_and_forged_intent_rejected_before_adapter`；gateways 无 store/ports/oms import | 通过 |
| NOT_SENT/UNKNOWN 带 callback 拒绝；SENT 空 callback 合法 | `GatewayDispatchResult.__post_init__` + verifier；`test_non_sent_certainties_require_empty_callbacks`；`test_protocol_and_sent_without_callback_are_valid` | 通过 |
| result command/attempt 与输入不一致拒绝；attempt bool/0/负/float 在 adapter 前拒绝 | `GATEWAY_RESULT_*_MISMATCH`；关键反例 claim=2/result=1 在 `test_result_command_and_attempt_are_fenced`；`test_attempt_rejected_before_adapter` | 通过 |
| callback 跨 command、identity 伪造、未来时间拒绝；同事件重复保留；同 id 异 payload fail closed | `test_callback_order_and_identical_duplicates_are_preserved`；`test_cross_command_forged_future_and_conflicting_callbacks_fail_closed`；同 id 异 payload 经 identity 失败为 `GATEWAY_CALLBACK_INVALID`（fail closed） | 通过 |
| 合同异常稳定脱敏且无 cause/context | `GatewayContractError(code)`；多处 assert `__cause__/__context__ is None`；hostile tz 不回显 secret | 通过 |
| WSL base + Windows Miniforge 定向 pytest/Ruff/mypy | 见 §4 | 通过 |

冻结 API 核对：`DispatchCertainty` 三态、`GatewayDispatchResult` frozen/slots、正真 `int` attempt、callbacks 仅 `tuple`、`GatewayTransport.submit` keyword-only、`validate_gateway_submit` / `verify_gateway_dispatch_result` 语义与白名单文件一致；未见生产 fake。

观察（非阻塞）：在当前 `ExecutionEvent` identity 覆盖全部 payload 字段的前提下，先跑 identity 再比 payload 时，`GATEWAY_CALLBACK_CONFLICT` 实际难达；同 id 异 payload 仍由 `GATEWAY_CALLBACK_INVALID` fail closed，满足合同“拒绝”语义。

## 3. 实现者未使用的对抗性反例

实现者覆盖 True/0/-1/float、SHADOW、forged intent/command、attempt fencing、重复 callback、跨 command/未来时间/forged identity、hostile tz、frozen mutate；**未覆盖** int 子类 attempt、duck-typed result、`occurred_at == observed_at` 边界，以及 mismatch 路径对 command/event 明文的脱敏抽查。

一次性探针（未写入测试文件；Windows Miniforge）：

1. `PosInt(2)`（`type is not int`）→ `GATEWAY_ATTEMPT_INVALID`，transport.calls=0
2. duck result（属性齐全但非 `GatewayDispatchResult`）→ `GATEWAY_RESULT_INVALID`，消息不含 command_id
3. `occurred_at == observed_at` → verifier 接受
4. 跨 command callback → `GATEWAY_CALLBACK_COMMAND_MISMATCH`，str 不含任一侧 command_id / broker id / symbol；cause/context 均为 None

结果：`ALL_ADVERSARIAL_OK`

## 4. 定向验证命令与结果

WSL Miniforge `base`：

- `pytest -q .../test_gateway_transport_contracts.py` → **17 passed**
- `ruff check` gateways + 该测试 → **All checks passed!**
- `mypy --no-incremental --cache-dir /tmp/quant-mypy-p2a-ext` 两源文件 → **Success: no issues found in 2 source files**

Windows `D:\Miniforge3\python.exe`：

- 同上 pytest → **17 passed**
- 同上 ruff → **All checks passed!**
- `mypy --no-incremental` 两源文件 → **Success: no issues found in 2 source files**

## 5. 初验结论与移交

- 初验：**通过**；冻结合同与双平台定向证据一致；对抗性反例未发现违约。
- 未验证/非本包：PaperGateway、OMS/store 映射、真实 IO、P2/P4/M4 Gate 关闭。
- 下一步：主 Agent 终验（SSOT/跨模块不变量/未公开反例/必要回归）；**不得**将本报告表述为 Gate 已关闭。
