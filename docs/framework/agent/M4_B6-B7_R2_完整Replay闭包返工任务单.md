# M4 B6/B7 R2：完整 replay 闭包返工任务单

日期：2026-08-02  
状态：设计冻结，进入实现

## 1. 阻断不变量

R1 公共 `verify_simulation_result_identity` 只证明调用者给出的结果“可构造且哈希自洽”，没有
证明 `rule_decisions` 是 B1/B2 对原计划、市场状态和当时账本状态的真实输出。攻击者删除全部 decision，
或把 `ACCEPTED` 换成语义相反的合法 decision，再重算 scenario/root identity，B6 仍通过，B7 也继续
产出指标。这破坏了 B6 → B7 的可信消费边界。

仅增加 decision 与 command id 的哈希映射仍不足，因为攻击者可以同时伪造 decision、映射和 root hash。
完整验证所需的原计划、市场快照、初始账户和仿真配置必须作为结果的公开、identity-bound replay 闭包保留，
公共 verifier 必须调用同一个 `simulate_order_plans` 公式重放，而不是复制规则或只检查哈希。

## 2. 冻结公共形态

在 `quant.backtest.event_simulator` 增加：

```python
@dataclass(frozen=True, slots=True)
class SimulationReplayInputs:
    replay_input_id: str
    plans: tuple[SimulationScenarioPlans, ...]
    snapshots: tuple[VerifiedMarketSnapshot, ...]
    initial_account: AccountSnapshot
    config: EventSimulationConfig
```

`VerifiedSimulationResult` 增加唯一字段：

```python
replay_inputs: SimulationReplayInputs
```

`replay_input_id` 使用现有 canonical identity helper 绑定：`config_id`、initial account snapshot id、按
顺序的 market snapshot ids，以及按顺序的 `(scenario_id, scenario_input_id)`。对象本体必须 clone/re-enter
既有公开构造器后保存；不得仅相信名义 ID。

`simulate_order_plans(...)` 在既有完整输入验证后构造 replay closure，并将其纳入 root identity。
`verify_simulation_result_identity(result)` 必须：

1. fail-closed 重验 replay closure 的名义类型、排序唯一性、所有嵌套公开 identity 和
   `replay_input_id`；
2. 使用 closure 原样调用同一个 `simulate_order_plans`；
3. 要求重放所得完整 `VerifiedSimulationResult` 与输入逐字段相等；
4. 任何异常统一为无 cause/context、无敏感正文的 `EVENT_SIM_RESULT_IDENTITY_INVALID`。

保留 `verify_simulation_result(result, plans, snapshots, initial_account, config)` 的显式外部输入接口；它仍
重放并逐字段比较。B7 不复制 replay 或规则公式，仍只调用 B6 公共 verifier。

## 3. 必须覆盖的反例

- 删除一个/全部 decision 后，即使重算 scenario/root identity也拒绝；
- 修改 accepted、code、normalized quantity/price、rule_version，并全量重哈希仍拒绝；
- decision 重复、乱序、跨 scenario 移植并全量重哈希仍拒绝；
- command/event/transition/checkpoint 任一删除、替换或移植并全量重哈希仍拒绝；
- replay closure 中 plan、snapshot、account、config 本体或 ID 漂移均拒绝；
- 合法、partial-fill、suspended、HK T+2 场景保持确定且验证通过；
- B7 对上述伪造输入在计算 metrics 前稳定抛 `TRADING_METRICS_INPUT_INVALID`；
- hostile 嵌套异常的 cause/context 和敏感 sentinel 不泄露。

## 4. 白名单与禁止项

可修改：

- `src/quant/backtest/event_simulator.py`
- `src/quant/backtest/__init__.py`
- `tests/unit/test_event_simulator.py`
- `src/quant/reporting/trading_metrics.py`（仅在类型适配确有必要时）
- `tests/unit/test_trading_metrics.py`
- 本任务交付报告

禁止修改 B1–B5 规则/账本公式、B8、execution、正式 G1/M3 路径、journal、真实数据或网络代码；不得新增
依赖。不得用私有签名、进程内 secret 或“调用者不知道 hash 公式”代替公开可重验闭包。

## 5. 验证与状态

Windows 先跑 B6/B7 定向 pytest、Ruff、mypy，再跑 B1–B8 合流定向。WSL base 因当前外部权限额度窗口
阻塞，不在本轮反复请求；Windows PASS 仅表示开发合同返工通过。独立复验通过前 B6/B7 仍为 FAIL；即使
通过，也不关闭正式数据 Gate、P8 soak、Linux Gate 或 M4。
