# M4-B3 开发示例成本与 FX 主 Agent 阶段验收报告

日期：2026-08-02

结论：**development/example 成本与 FX 契约通过；正式费率/FX 数据源与正式 M4 Gate 尚未验收。**

## 变更

- `backtest.costs` 新增严格的多市场 `ExecutionCostPeriod` / `ExecutionCostSchedule` 与 `calculate_execution_cost`。
- 实际成交价和成交量形成费用基数；佣金、卖方税和过户费分别生成公共 `FeeComponent`，法定费用显式标记 `statutory=true`。
- 最低佣金和所有币种金额采用 `Decimal` + `ROUND_HALF_UP` 分币量化；不同商业佣金场景不缩放法定费率。
- 新增 `backtest.fx`：有身份摘要的只读 `FxSnapshot`、唯一方向 `FxRate`、`convert_money` 和显式时点新鲜度验证。
- FX 缺失、过期、反向推导、重复方向、伪造身份、费用有效期重叠及 hostile selector 均失败闭合；不做隐式逆汇率。
- `quant.backtest` 导出公共入口，供订单规划、账本和统一事件回测复用。

## 验证

Windows 原生 Miniforge：

```text
pytest tests/unit/test_m4_costs_fx.py -q
6 passed
pytest tests/unit/test_etf_simulator.py tests/unit/test_m3_a_share_simulator.py tests/unit/test_m4_costs_fx.py -q
14 passed
ruff check src/quant/backtest/costs.py src/quant/backtest/fx.py src/quant/backtest/__init__.py tests/unit/test_m4_costs_fx.py
All checks passed!
mypy src/quant/backtest/costs.py src/quant/backtest/fx.py tests/unit/test_m4_costs_fx.py
Success: no issues found in 3 source files
```

WSL Miniforge `base`，DrvFS `/mnt/f` 定向反馈：`6 passed`，Ruff 与 mypy 通过。Windows pytest cache ACL 与 Pandera deprecation 为既有告警，不改变测试结论。

## 边界

- 本实现无网络、无真实 FX/券商调用，不读取 `data/legacy`，不接触正式 G1 journal 或发布目录。
- development/example 费用只证明公共合同、量化和失败语义；真实费率来源、正式 G7 绑定、ext4 Gate 和正式发布仍保持打开。
