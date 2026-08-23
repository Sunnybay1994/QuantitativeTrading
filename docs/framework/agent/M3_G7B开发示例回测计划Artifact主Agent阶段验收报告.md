# M3 G7B development example 回测计划 Artifact 阶段验收

日期：2026-08-02

## 结论

G7B development example 工程合同已实现，并通过 Windows 与 WSL Miniforge base 定向验证。它证明 verified G7A target 可以按权威 SH 开市日历调度为严格下一 session 的回测计划，并发布稳定成本日程、manifest 与 receipt；不代表正式回测收益、真实 G7B 或 Linux/ext4 Gate 已关闭。

## 实现边界

- 每个完整 signal-date batch 精确映射到共同的严格下一 SH open session；尾部缺少下一 session、非 signal 行、mixed work/strategy 或非 A 股证券均 fail closed。
- `BacktestWindow` 固定记录 signal/execution dates、首个 execution、terminal close 和 `force_liquidation=false`；末次 execution 同时作为 terminal valuation session。
- `scheduled_targets.parquet` 精确为 TargetWeightSchema 五列加 `execution_date`，按 `execution_date,as_of,symbol` 排序；diagnostics 精确为五列且 `session_lag=1`。
- 成本日程从 scientific config 投影，闭区间连续、无重叠、开放末段唯一；`0.5/1/2` 只缩放 commission rate/min 与 slippage，stamp tax/transfer fee 保持历史事实值。
- 所有配置数值经 `Decimal(str(value))` 转换，JSON 日期使用 ISO 字符串、Decimal 使用无指数 canonical 十进制字符串。
- 输出树严格只有 scheduled targets、diagnostics、cost schedule 和 manifest；receipt 固定为 `development-backtest-plan` / `WORK`，精确绑定 11 个输入和 4 个输出。
- capability 固定 `development_example` / `formal_gate_eligible=false`；verifier 重算日历、调度、成本、manifest、上游 bytes 与 receipt 闭包。

## 对抗验证

覆盖严格下一 session、完整 signal batch、window 首尾、精确 schema/排序、成本连续性与三档倍数、尾部缺 session、非 signal、跨 work/strategy、HK 混入、no-clobber、development identity 混用、11/4 receipt 闭包、四输出及 receipt 单项篡改，以及核心 import 不加载 Qlib。

```text
Windows pytest: 10 passed in 227.57s
WSL base pytest: 10 passed in 124.02s
Windows Ruff:   All checks passed
Windows mypy:   Success: no issues found in 3 source files
WSL base Ruff:  All checks passed
WSL base mypy:  Success: no issues found in 5 source files
```

## 尚未关闭

- G7C-G7F entitlement、订单/成交、账户模拟与情景发布；
- 正式 G7B 对正式研究链 artifacts 的发布；
- 真实收益、性能、Linux/ext4 与正式 Gate 结论。
