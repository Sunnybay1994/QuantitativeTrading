# M4-B1 开发示例 A 股规则适配主 Agent 阶段验收报告

日期：2026-08-02
结论：**development/example 契约通过；正式 M4-B1 闭包仍等待正式 M3-G7。**

## 变更与理由

- 在 `quant.backtest.a_share_execution` 增加 `AShareRuleConfig`、严格构造器和 `evaluate_a_share_intent` 公共适配入口。
- 适配器直接复用 G7D 的 `resolve_a_share_order_quantity_rule`、`largest_valid_buy_quantity` 与 `largest_valid_sell_quantity`，没有复制第二套板块或数量规则。
- 输入通过 M4 公共构造器重建并核验身份；跨市场、伪造身份、路径化 selector 统一失败为 `A_SHARE_RULE_INPUT_INVALID`。
- 决策覆盖主板、创业板、科创板数量差异，整仓零股卖出、T+1、停牌、精确涨跌停边界、价格档位、规则版本和闭区间生效日。
- `src/quant/backtest/__init__.py` 导出新公共接口，供后续订单计划与纸面交易链正常消费。

## 验证证据

Windows 原生 Miniforge（隔离 worktree `PYTHONPATH=src`）：

```text
python -m pytest tests/unit/test_m4_a_share_rules.py -q
11 passed
python -m ruff check src/quant/backtest/a_share_execution.py src/quant/backtest/__init__.py tests/unit/test_m4_a_share_rules.py
All checks passed!
python -m mypy src/quant/backtest/a_share_execution.py tests/unit/test_m4_a_share_rules.py
Success: no issues found in 2 source files
```

WSL Miniforge `base`，DrvFS `/mnt/f` 定向反馈环：

```text
python -m pytest tests/unit/test_m4_a_share_rules.py -q
11 passed
python -m ruff check ...
All checks passed!
python -m mypy ...
Success: no issues found in 2 source files
```

Windows pytest 的 `.pytest_cache` ACL 告警不影响测试结论。WSL 本次运行位于 DrvFS，只证明 Linux 解释器合同兼容性，不替代 ext4 Gate。

## 边界与剩余风险

- 本阶段只消费不可混淆的 development/example G7 工程契约；没有读取或写入正式 G1 journal、正式候选目录或正式发布根。
- 正式 M3-G7 尚未完成，因此本报告不宣称正式 M4-B1、M4 或 Linux Gate 已通过。
- 后续 B4/B5 可在开发示例链上继续集成；正式发布、性能结论与 Gate 关闭仍须绑定正式 G7/G8 产物并复验。
