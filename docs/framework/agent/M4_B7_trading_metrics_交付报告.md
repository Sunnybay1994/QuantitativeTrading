# M4-B7 trading metrics 交付报告

## 结论

已按任务书冻结的 B7 边界实现纯内存、确定性的交易与分币种账面指标。实现直接消费 B6
`VerifiedSimulationResult`，不重算成交、费用、结算、公司行动或 FX，也不生成或部署策略。

独立初验发现首版仅检查名义类型和 root id 形态，未证明 B6 结果身份闭包。P1 返工已在 B6 增加公开
`verify_simulation_result_identity`：无需完整 replay inputs 即可重验嵌套公开合同、transition/checkpoint
链路、scenario 排序唯一性，并重算 scenario/root identity。B7 计算前只调用该公共入口，不复制 B6 私有
hash 公式。新增 forged root id、scenario rename、scenario 增删/重复及 B7 fail-closed 回归。

## 实现范围

- `src/quant/reporting/trading_metrics.py`
  - `build_trading_metrics(result, annualization_sessions) -> TradingMetrics`
  - `TradingMetrics`、`ScenarioTradingMetrics`、`CurrencyTradingMetrics`
  - 稳定错误 `TRADING_METRICS_INPUT_INVALID`
  - canonical JSON + SHA-256 内容身份
- `src/quant/reporting/__init__.py`：仅安全导出上述公共接口。
- `src/quant/backtest/event_simulator.py`、`src/quant/backtest/__init__.py`：B6 结果 self-consistency
  verifier 及安全导出。
- `tests/unit/test_trading_metrics.py`：覆盖零交易、部分成交、费用、非零账面回撤、年化波动率、
  NaN、除零、非法 annualization 与确定 identity。
- `docs/framework/agent/M4轻量交易闭环分包任务书.md`：冻结计算口径及禁止混用边界。

## 关键边界

账面曲线按币种计算 `settled + receivable - payable + position cost`；不同币种不聚合。它用于验证账本与
执行路径，不冒充市价 NAV。B6 当前不携带 checkpoint 市价和逐时 FX，因此本包不输出市场收益、Sharpe、
Calmar，也不向 B8 提供可自动放行的正式绩效结论。

## 验证

Windows 原生 `D:\Miniforge3\python.exe`：

- `ruff check`（实现、导出、B7 测试）：通过。
- `mypy`（实现、导出、B7 测试）：`Success: no issues found in 3 source files`。
- `pytest test_trading_metrics.py test_event_simulator.py -q`：`16 passed`。
- `pytest test_quantstats_report.py test_trading_metrics.py -q`：`9 passed`，既有 reporting 入口未回归。

WSL Miniforge `base`：

- 对应定向 Ruff：通过。
- 对应定向 mypy：`Success: no issues found in 3 source files`。
- 对应 B7+B6 pytest：`16 passed`。

固定 partial-fill fixture 的 `metrics_id` 为
`89df553c387137d041f9f10147d3962e84aff4c3b4de3f8be59e293347130915`；该断言已在 Windows 与 WSL
同一测试中通过。两平台均有 Pandera 既有 deprecation warnings；Windows 另有 worktree `.pytest_cache`
权限 warning，不影响测试结果。

P1 身份闭包返工后的最终定向集合扩展为 B6 event simulator、B7 metrics、ledger、execution contracts 与
既有 QuantStats reporting：Windows 与 WSL base 均为 `76 passed`；最终 Ruff 均通过，mypy 均为
`Success: no issues found in 6 source files`。Windows pytest 仍仅有上述既有 cache/deprecation warnings，
WSL 仅有既有 Pandera deprecation warnings。
