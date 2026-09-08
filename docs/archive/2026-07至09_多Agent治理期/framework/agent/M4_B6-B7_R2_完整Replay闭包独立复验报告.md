# M4 B6/B7 R2：完整 replay 闭包独立复验报告

日期：2026-08-08  
角色：未参与 R2 实现的全新独立复验 Agent  
写入边界：生产代码与实现者测试只读；仅写本报告

## 1. 结论

| 子包 | 结论 | 说明 |
|---|---|---|
| M4-B6 | **PASS（Windows/WSL DrvFS 开发合同）** | replay closure 会重验嵌套公开 identity，公共 verifier 确实调用同一个 `simulate_order_plans` 完整重放并逐字段比较；独立全量重哈希伪造均被拒绝，hostile 异常也已断链脱敏。 |
| M4-B7 | **FAIL** | 输入伪造会在指标公式前拒绝，但 verifier 抛 hostile 异常时，`TradingMetricsError.__context__` 仍保留原始异常及敏感 sentinel，违反 R2 的异常断链合同。 |

B6/B7 R2 总体结论为 **FAIL**。不得据此宣布 B6→B7 闭环、P8、Linux/ext4 或 M4 Gate 通过。

## 2. 合同与代码映射

### 2.1 replay 闭包和同公式重放

- `SimulationReplayInputs` 公开保留 plans、snapshots、initial account、config，并用 `replay_input_id` 绑定 config、账户、顺序化 snapshot 和 scenario input identity。
- `_build_replay_inputs` 通过既有公开构造器 clone/re-enter 计划、市场快照、账户和配置；`_prove_replay_inputs` 再构造并比较本体，不只相信名义 ID。
- root `VerifiedSimulationResult` identity 纳入 `replay_input_id`。
- `verify_simulation_result_identity` 先执行结构与嵌套 identity 重验，再从 replay closure 直接调用模块中的同一个 `simulate_order_plans`，最后比较完整结果对象；没有复制 B1/B2、成本或账本公式。
- 独立运行时包装该模块入口后，合法验证记录 `SAME_SIMULATE_CALL 1`，证明公共 verifier 实际调用该公式一次。

### 2.2 B7 的消费顺序

- `build_trading_metrics` 先调用 B6 公共 verifier，再进入 `_build_scenario`。
- 独立把 `_build_scenario` 包装为计数器后输入全量重哈希伪造结果，得到 `TRADING_METRICS_INPUT_INVALID` 且计数为 `0`；因此伪造输入确实在任何指标计算前被拒绝。
- B7 没有复制 replay、规则、成交、费用或账本公式。

## 3. 独立对抗复验

独立探针没有调用实现者的 `_fully_rehash_result`，而是直接使用公开字段和当前 canonical identity 规则重算 scenario/root identity；临时探针运行后已删除，未留下生产或测试文件。

| 反例 | 实际结果 |
|---|---|
| decision 全删、合法字段替换、重复、移植 suspended 场景 decision，并重算 scenario/root | 全部稳定拒绝 `EVENT_SIM_RESULT_IDENTITY_INVALID` |
| command 删除、重复、移植另一场景命令，并重算 scenario/root | 全部稳定拒绝 |
| event 删除、重复、移植另一场景事件，并重算 scenario/root | 全部稳定拒绝 |
| transition 删除、重复、移植另一场景 transition，并重算 scenario/root | 全部稳定拒绝 |
| checkpoint 删除、重复、移植另一场景 checkpoint，并重算 scenario/root | 全部稳定拒绝 |
| plan 本体及其 scenario input identity 一起变化，重算 replay/scenario/root | 稳定拒绝 |
| snapshot 本体及 snapshot/checkpoint/replay/root identity 一起变化 | 稳定拒绝 |
| initial account 本体及 account/replay/root identity 一起变化 | 稳定拒绝 |
| config 本体及 config/replay/root identity 一起变化 | 稳定拒绝 |
| replay nominal identity/对象形态破坏 | 稳定拒绝 |
| B7 消费上述 decision 全量重哈希伪造 | `TRADING_METRICS_INPUT_INVALID`，指标构建调用次数为 0 |
| B6 重放入口抛含 `C:/TOKEN_INDEPENDENT_SENTINEL` 的 hostile 异常 | 公开错误仅为 `EVENT_SIM_RESULT_IDENTITY_INVALID`；cause/context 均为 `None` |
| B7 的 B6 verifier 抛同一 hostile 异常 | 公开文字为稳定码，但 `__context__ == RuntimeError('C:/TOKEN_INDEPENDENT_SENTINEL')`，**FAIL** |

## 4. 阻断问题：B7 hostile 异常上下文未断开

### 现象

将 `quant.reporting.trading_metrics.verify_simulation_result_identity` 临时替换为抛出
`RuntimeError("C:/TOKEN_INDEPENDENT_SENTINEL")` 的 hostile verifier，再调用合法结果的
`build_trading_metrics(result, 252)`，捕获到：

```text
B7_HOSTILE_CHAIN TRADING_METRICS_INPUT_INVALID None RuntimeError('C:/TOKEN_INDEPENDENT_SENTINEL')
```

外层异常字符串虽然稳定，但调用者可从 `error.__context__` 取回敏感正文；打印 traceback 时也会输出该 sentinel。

### 根因

`src/quant/reporting/trading_metrics.py` 的 `build_trading_metrics` 在 `except Exception:` 活跃异常作用域内直接调用
`_fail()`。`_fail()` 使用普通 `raise TradingMetricsError(...)`，因此 Python 自动把 hostile 原异常挂到
`__context__`。这与 B6 已采用的“先退出 except，再抛稳定错误”模式不一致。

### 应遵循规则

R2 任务冻结要求 hostile 嵌套异常的 cause/context 和敏感 sentinel 不泄露。公开 B7 边界不仅要隐藏错误正文，
还必须切断异常对象链；指标消费者不得通过 `__context__` 或 traceback 观察下游 hostile payload。

### 最小复现

```python
result = simulate_order_plans(*fixture)
trading_metrics.verify_simulation_result_identity = hostile_verifier
try:
    build_trading_metrics(result, 252)
except TradingMetricsError as error:
    assert error.__context__ is None  # 当前失败，context 为 hostile RuntimeError
```

### 必须新增的测试

1. verifier 抛含路径/token sentinel 的普通异常时，B7 只抛 `TRADING_METRICS_INPUT_INVALID`；
2. `str(error)`、`repr(error.__cause__)`、`repr(error.__context__)` 均不得泄露 sentinel；
3. `error.__cause__ is None` 且 `error.__context__ is None`；
4. hostile verifier 失败时 `_build_scenario` 调用次数仍为 0；
5. 合法、partial-fill、suspended 与不可计算指标回归保持绿色。

### 通过条件

最小修复 B7 异常映射，使非 `TradingMetricsError` 的失败在离开 active `except` 后统一抛稳定、无 cause/context 的
`TRADING_METRICS_INPUT_INVALID`；新增上述回归后，由未参与修复的新独立 Agent 再次复验。

## 5. 验证证据

### Windows 原生 Miniforge

- B6/B7 定向 pytest：`31 passed`（`23.11s`）。
- B1–B8 合流定向 pytest：`172 passed`（`29.90s`）。
- Ruff（B6/B7 生产、导出与测试文件）：`All checks passed!`。
- mypy（`event_simulator.py`、`trading_metrics.py`）：`Success: no issues found in 2 source files`。
- `git diff --check`：无空白错误；只有 Windows checkout 的 LF→CRLF 提示，未执行转换。

### WSL Miniforge base

在同一 `/mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g8ab-prereq` 路径运行 B6/B7 定向 pytest：
`31 passed`（`20.10s`）。该路径属于 DrvFS，仅证明 WSL base 解释器下的对应开发合同兼容，不等同于 ext4
平台 Gate。

上述测试存在 Pandera/Polars 已知 deprecation warnings，不改变本次断言结果。

## 6. 边界与下一步

- 本轮未修改 B1–B8 生产代码或实现者测试，未访问网络、真实数据、正式 G1/M3 目录或 journal。
- B6 replay 全闭包核心返工通过独立开发合同复验；返工时应保持其实现和测试只读。
- B7 修复并新增 hostile 断链测试前，B6/B7 R2 仍为 FAIL。
- 即使后续复验通过，也只表示开发合同通过；正式数据、真实性能、P8 soak、Linux/ext4 与 M4 总 Gate 仍分别保持开放。
