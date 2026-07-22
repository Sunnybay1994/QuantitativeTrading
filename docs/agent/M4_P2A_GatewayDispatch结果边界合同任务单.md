# M4-P2A Gateway Dispatch 结果边界合同任务单

状态：2026-07-18 冻结；24 小时临时流程内由主 Agent 实现、内部子 Agent 独立审查

## 1. 目标与非目标

目标：在 P4 service 与未来 Paper Gateway 之间建立最小、无 IO 的确定性边界，使调用方能区分请求确定未发送、
确定已发送和发送结果未知，并把 P4-P0 claim 的 attempt 作为 fencing generation 闭合到返回值。

非目标：不实现 `PaperGateway`、连接/重连状态机、延迟 callback 队列、fault plan、fill/slippage/fee/FX、
市场规则拒单、取消或 durable recovery；不修改 OMS/store/领域 SSOT，不关闭 P2/P4/M4 Gate。

## 2. 权威上下文与架构边界

- `src/quant/execution/contracts.py`：`OrderCommand`、`ExecutionEvent` 及公开 identity verifier。
- `src/quant/execution/store.py`：P4-P0 delivery attempt fencing 与 `SENT/UNKNOWN` 存储语义；本包不得 import store。
- [`M4轻量交易闭环分包任务书.md`](M4轻量交易闭环分包任务书.md) P2/P4。
- gateway 子包只能依赖 execution/domain 窄合同，不依赖数据 connector、portfolio/backtest 或 broker SDK。

## 3. 冻结 API 与语义

- `DispatchCertainty = NOT_SENT | SENT | UNKNOWN`。
- `GatewayDispatchResult(command_id, dispatch_attempt, certainty, callbacks)`：不可变；attempt 为正真 int；
  callbacks 必须为 tuple。
- `GatewayTransport` runtime-checkable Protocol：
  `submit(*, command, dispatch_attempt, now) -> GatewayDispatchResult`。
- `validate_gateway_submit(command, dispatch_attempt, now)`：在 adapter 调用前重算 command/intent identity；只允许
  `ExecutionMode.PAPER`；attempt 为正真 int；now 必须 aware UTC。SHADOW 必须在 adapter call count 变化前拒绝。
- `verify_gateway_dispatch_result(command, dispatch_attempt, observed_at, result)`：重验输入 command、result 类型、
  command id、attempt、certainty 与 callback 闭包。

三态：

- `NOT_SENT`：请求确定未离开 adapter 边界；callbacks 必须为空；不得伪造成 OMS `REJECTED`。
- `SENT`：请求已进入 gateway；callbacks 可为空（ACK 延迟）或包含按 adapter 观察顺序排列的事件。
- `UNKNOWN`：请求可能已发送但结果不可判定；callbacks 必须为空；未来 P4 必须映射 outbox UNKNOWN，禁止自动重试。

callback 规则：每项必须是 identity 可重算的 `ExecutionEvent`，command id 与输入一致，`occurred_at <= observed_at`；
不排序、不去重。相同 event id+相同 payload 的重复 callback 原样允许；相同 event id 异 payload fail closed。

所有合同错误使用稳定 `GatewayContractError(code)`；不得回显 command/event/payload/路径，且实际
`__cause__`/`__context__` 均为 None。

## 4. 白名单与禁止项

可写：

- 新建 `src/quant/execution/gateways/__init__.py`
- 新建 `src/quant/execution/gateways/contracts.py`
- 新建 `tests/unit/test_gateway_transport_contracts.py`
- 本任务和对应最终验收报告；必要状态文档

禁止修改 `execution/contracts.py`、`ports.py`、`oms.py`、`store.py`、domain enums；禁止新增依赖和生产 fake。
测试 fake 只能存在于测试文件。

## 5. 成功标准与反例

- [ ] forged command/intent 在 adapter 前拒绝；SHADOW call count=0。
- [ ] NOT_SENT/UNKNOWN 携带 callback 拒绝；SENT 空 callback 合法。
- [ ] result command/attempt 与输入不一致拒绝；attempt 的 bool/0/负数/float 在 adapter 前拒绝。
- [ ] callback 跨 command、identity 伪造、未来时间拒绝；相同事件重复保留，同 id 异 payload拒绝。
- [ ] 合同异常稳定脱敏且无 cause/context。
- [ ] WSL base 与 Windows Miniforge 定向 pytest/Ruff/mypy 通过。

关键反例：claim attempt=2，而 adapter 返回 attempt=1；post-verifier 必须拒绝，不能让未来 service 错误地
以旧 generation 标记 P4-P0 delivery 终态。

## 6. 后续依赖

P2B full Paper Gateway 仍等待 B1/G7D、B2、B3 以及 `CancelRequest` identity；P4 service 仍等待 B4/P2B。
本包只允许未来 P4 明确映射：NOT_SENT→不落终态并等待 lease；SENT→先持久化 callbacks 再标 SENT；
UNKNOWN→标 UNKNOWN 并进入人工查询/对账。
