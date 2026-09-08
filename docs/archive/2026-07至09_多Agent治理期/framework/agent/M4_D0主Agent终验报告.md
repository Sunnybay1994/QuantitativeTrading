# M4-D0 主 Agent 终验报告

日期：2026-07-16  
结论：**不通过，退回“外部实现 → 全新外部独立初验”闭环**  
范围：M4-D0 领域合同、strict constructor 与 identity closure  
声明：不关闭 M4/Gate，不勾选路线图；D1/P0/P1/P3 继续视为基于 D0 待返工合同的预实现

## 1. 已复核证据

- 冻结合同：[`M4轻量交易闭环分包任务书.md`](M4轻量交易闭环分包任务书.md) §2–§3、M4-D0。
- 外部交付：[`M4_D0领域合同交付报告.md`](M4_D0领域合同交付报告.md)。
- 外部独立初验：[`M4_D0领域合同独立初验报告.md`](M4_D0领域合同独立初验报告.md)，结论可交主验。
- 主 Agent 复跑 `tests/unit/test_execution_contracts.py`：**12 passed**。
- 未跑全量 pytest；纯内存隐藏反例已经证明核心闭包不成立。

## 2. 主验新增反例

### P0-A：OrderPlan 顶层来源身份未约束内部 intent

- **现象**：`build_order_plan` 接受 top-level target/market/account/config 四个 identity 与
  `OrderIntentSpec` 中四个 identity 全部不同的输入，仍返回自洽 `plan_id`。
- **根因**：plan digest 同时哈希两组矛盾事实，却没有要求每个 intent 的来源闭包等于 plan 顶层来源；
  “都被哈希”被错误地当作“语义一致”。
- **最小结果**：`PLAN_NESTED_IDENTITIES_MISMATCH_ACCEPTED True True True True`。
- **影响**：下游无法判断订单究竟基于哪份 target、market/account snapshot 或 config 产生。

### P0-B：ExecutionEvent 数量上限信任调用方自报

- **现象**：真实 `OrderCommand.intent.quantity=10`，调用 event builder 时自报
  `command_quantity=1000`，可生成 `cumulative_quantity=500` 的合法事件。
- **根因**：builder 只接收 `command_id` 与未纳入 identity、未被验证的裸 `command_quantity`，没有消费
  自证的 `OrderCommand`。
- **最小结果**：`EVENT_EXCEEDS_REAL_COMMAND_ACCEPTED 10 500`。
- **影响**：D0 声称的“累计量不超过 command quantity”可被调用方绕过，P1/P0 的幂等与账本数量基础失真。

### P1-C：VerifiedMarketSnapshot 允许交易日混配

- **现象**：snapshot `session_date=2026-07-16`，内部 state 为 `2026-07-15`，builder 接受并生成 verified ID。
- **根因**：snapshot 只检查 state key 唯一，没有逐项绑定 `state.session_date == snapshot.session_date`。
- **最小结果**：`SNAPSHOT_DATE_MISMATCH_ACCEPTED 2026-07-16 2026-07-15`。
- **影响**：订单规则可能用错交易日的停牌、涨跌停、board lot 或额度状态。

### P1-D：strict builder 在嵌套类型门禁前访问属性

- **现象**：`OrderIntentSpec.market="SH"` 时，`build_order_plan` 在排序阶段抛 `AttributeError`，不是稳定
  `ContractError`。
- **根因**：公开 helper 没有 `__post_init__`，多个 builder 在验证 element 类型前先排序或构造 digest。
- **最小结果**：`BAD_SPEC_EXCEPTION_TYPE AttributeError False`。
- **影响**：不可信/错误输入绕过统一失败语义，并可能把底层实现细节带入 CLI/日志。

## 3. 结论

正常路径和既有 12 项测试通过，但来源、时间和数量三条核心闭包均可被构造器接受的输入破坏。M4-D0 当前为
**主验不通过、待外部返工**。D1/P0/P1/P3 不必撤销代码，但只能作为预实现；D0 修复并复验前不对它们作最终
通过结论。返工合同见 [`M4_D0主验返工任务单.md`](M4_D0主验返工任务单.md)。
