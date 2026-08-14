# M4 P8 RUN-0B2F-S2 R1 Formal Gateway Policy Adapter 任务单

状态：主 Agent 串行实现与 Windows 正常开发检查已完成；formal service composition 已解锁；未宣称 runner、soak、Linux 或 M4 Gate 完成。

## 1. 目标与前置

在已完成的 formal runtime、execution policy、broker binding、account、durable broker store 与只读 snapshot port 之上，提供唯一的 formal PAPER gateway factory。该 factory 必须消费完整 fresh formal chain，复用现有 `DurablePaperGatewayFactory`、`PaperGateway`、费用引擎和 B1 store，不复制 SQLite、OMS reducer 或费用算法。

本任务只闭合 policy adapter 与 gateway dispatch；不实现 service/CLI composition、runner、soak、fault-drill 配置或实盘 gateway。

## 2. 用户批准的业务语义（UA-M4-003）

1. 正常 submit 只接受现有 PAPER DAY limit command；产生唯一全量 fill，价格严格等于 `command.intent.limit_price`，数量严格等于 `command.intent.quantity`，回报顺序为 `ACCEPTED -> FILL`，费用由 verified cost schedule 计算。
2. 正常 cancel 使用 `late_fills=()`、`confirm_cancel=True`，回报顺序为 `CANCEL_ACCEPTED -> CANCELLED`；已全成订单继续由既有 OMS/command contract fail closed。
3. 正常 fault plan 对 submit/cancel 均返回 `SENT`，duplicate ordinals 为空。`NOT_SENT`、`UNKNOWN` 和 exact duplicate 仅允许未来显式、版本化、按 operation identity + attempt 配置的 drill；本任务不猜配置结构，也不启用任何 drill。
4. 每次 dispatch 使用 service 传入的唯一 aware UTC `now` 作为 `observed_at`；本次 dispatch 的所有 callbacks 使用完全相同的时间，tuple/OMS sequence 表达顺序。retained replay 只返回已持久化结果，不再次读取时钟。
5. 不读取 wall clock，不使用随机数或进程内计数器决定业务结果。

## 3. Public API 与稳定失败

新增模块 `quant.execution.paper_formal_gateway`，只公开：

- `FormalPaperGatewayError`
- `open_verified_formal_paper_gateway_factory(*, store_capability, environment, policy, binding, account, now) -> PaperGatewayFactory`

入口及返回 factory 的 `identity()`、`open()`，以及返回 gateway 的每次 `submit()`/`cancel()` 都必须通过 public `verify_existing_formal_paper_broker_store_capability` fresh 验证同一个 exact store capability。dispatch 以调用参数 `now` fresh 验证，并把该值传给 event-time 逻辑。

所有 public 失败统一为 `PAPER_FORMAL_GATEWAY_INVALID`，`__cause__`/`__context__` 均为空；不得泄露 path、hash、账户、SQLite 或 hostile exception 内容。

## 4. 实现边界

- formal fill/fault/clock adapter 均为模块私有，caller 无入口传入或替换。
- exact 支持版本：`paper_deterministic_fill_v1`、`paper_controlled_fault_drills_v1`、`utc_system_clock_v1`；其他值 fail closed。
- B1 formal policy descriptor 只能通过 `build_formal_paper_broker_policy_descriptor(policy, binding)` 产生。
- `DurablePaperGatewayFactory` 新增窄的 formal construction path；development constructor、descriptor identity 和既有行为保持不变。
- `PaperGateway` 的 development `PaperClock.event_time()` 契约保持不变；新增独立 dispatch-anchored clock protocol/path，只有 formal adapter 使用。submit/cancel 首次生成 callbacks 时显式传入本次 `now`；retained durable replay仍在调用 ephemeral clock 前返回。
- 不新增第二套 store、费用、reducer、gateway result 或 evidence 实现。

## 5. 文件白名单

- `src/quant/execution/gateways/paper.py`
- `src/quant/execution/gateways/paper_durable.py`
- `src/quant/execution/paper_formal_gateway.py`（新增）
- `src/quant/execution/__init__.py`
- `tests/unit/test_paper_formal_gateway.py`（新增）
- 本任务单与唯一交付报告

若必须修改 runtime/policy/binding/account/store/snapshot/service/CLI/runner/soak/config/schema/enums，立即停止并重新冻结。

## 6. 最小反例与正常开发检查

定向测试至少覆盖：

- fresh formal chain 正向 submit：exact `ACCEPTED -> FILL`、全量、limit price、费用、同一 dispatch timestamp；
- retained retry 返回逐字段相同结果且不再调用 formal clock/fill/fault adapter；
- 正常 cancel 对明确未全成状态产生 `CANCEL_ACCEPTED -> CANCELLED`；默认 submit 全成后 cancel 由现有契约拒绝；
- unsupported selector、formal/dev 混配、stale/closed store、cross-chain、fake/subclass、hostile verifier 均稳定脱敏拒绝；
- development gateway 原时钟 ordinal 行为不变。

开发检查依次运行 focused pytest、相邻 durable gateway pytest、定向 Ruff、定向 mypy、cold import。当前阶段只要求 Windows 开发证据；Linux/ext4 与正式 PAPER Gate 仍开放。

## 7. 完成边界

完成本任务只解锁 formal service composition 的下一包，不代表 runner、soak、PAPER 候选或 M4 Gate 完成。
