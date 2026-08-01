# M3 G7P0 回测舍入与年化 Scientific 配置增量阶段验收

日期：2026-08-02

## 结论

G7P0 已完成。`backtest.a_share` 新增四个必填 scientific selector：

- `execution_price_rounding = "BUY_CEIL_SELL_FLOOR_TICK_V1"`
- `fee_rounding = "EACH_COMPONENT_HALF_UP_CENT_V1"`
- `cash_settlement_rounding = "HALF_UP_CENT_V1"`
- `annualization_sessions = 252`

缺字段、未知枚举、邻近整数以及 bool 冒充 int 均 fail-closed；四项参与
`scientific_config_sha256`，G7 后续实现不得硬编码另一套口径。

## 同步修复的 SSOT 漂移

进入 G7P0 前，生产 `_FIELD_SPECS` 与示例配置已经有 144 shapes / 157 leaves，但配置测试仍保留更早的
141 / 154 断言，导致该单测真实失败。此次在不删除既有字段的前提下，将加入四项后的闭包固定为
148 shapes / 161 leaves，并同步修正测试。任务单早期写的 138→142 已被后续 C0 增量超越，当前代码与
示例配置的实际闭包是权威证据。

## 验证

```text
Windows Miniforge: tests/unit/test_m3_config.py  89 passed in 5.18s
WSL base:          tests/unit/test_m3_config.py  89 passed in 3.10s
Ruff:              All checks passed
mypy:              Success: no issues found
```

这只是 G7 配置前置，不关闭 G7A–G7F、production G7 或正式 Gate。
