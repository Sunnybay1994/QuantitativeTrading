# M3 G7E 开发示例账户循环主 Agent 阶段验收报告

日期：2026-08-02

## 结论

G7E 的开发示例账户循环合同通过。后续 G7F 可通过公开接口消费同一份 verified development release、
回测计划与 A 股市场事实，生成三场景结果和发布收据。本结论只证明开发契约与 Windows/WSL 运行兼容性，
不等同于正式数据回测验收、正式 G1 Linux/ext4 Gate 或 M3 发布通过。

## 已实现

- `simulate_a_share_scenario` 只接受经过验证的 development target、backtest plan 和 market-facts 类型；
  `development_example` 与 `formal_gate_eligible=False` 身份贯穿结果，不能伪装为正式发布。
- 每个交易日严格按 rollover、公司行动确认/结算、盘前估值、卖出、买入、收盘估值、record-close capture
  顺序推进；当日卖出所得可用于当日买入，但 A 股卖出仍服从 T+1 可卖数量。
- FULL_DAY 停牌持仓沿用上一可用估值；无停牌证据的持仓缺 bar 会 fail-closed；末日不强制平仓。
- 公司行动 capture、recognize、settle 均写入可审计 posting，现金、持仓、应收权益和 NAV 使用 Decimal
  重算；输出浮点列只是固定 schema 的序列化投影。
- 输出固定为七张排序表：NAV、成交、持仓、拒绝、公司行动分录、逐日诊断、权益快照；七个 Pandera schema
  固化列集、唯一键、有限值、非负和基本守恒约束。
- 输入行顺序变化不影响结果；目标 manifest 漂移和 development example identity 混用均 fail-closed。
- 全路径无网络、无 Tushare/BaoStock、无 Qlib import，也不写正式 G1 journal、候选目录或发布根。

## 验证

Windows 原生 Miniforge：

```text
pytest tests/unit/test_m3_a_share_simulator.py
       tests/integration/test_m3_a_share_simulator_golden.py
8 passed in 62.93s
ruff check <G7E changed files>
All checks passed!
mypy <G7E source files>
Success: no issues found in 4 source files
```

WSL Miniforge base（源码在 `/mnt/f`，不是 ext4 Gate）：

```text
pytest <same G7E tests>
8 passed in 32.76s
ruff check <same G7E files>
All checks passed!
mypy <same G7E source files>
Success: no issues found in 4 source files
```

Pandera/Polars 产生已知弃用警告；Windows pytest cache 另有工作树 ACL 警告，均未改变测试结果。

## 剩余风险与下一步

- 当前公开 development plan 只有两个交易日；G7E 已覆盖分红、轮换、停牌和顺序不变量，但正式要求的
  多证券、至少五个 session 的三场景发布矩阵须在 G7F 构造并由 receipt verifier 闭包。
- development consumer 仍只接受明确的 development verified 类型；正式 G7 折叠须增加正式
  `VerifiedG1Release` 路径并在真实 release 上重跑，不能通过类型替换混用。
- 正式 G2C 已完成；正式 G3A 发布仍依赖 G8 ExperimentIdentity 前置合同，且正式 G1 Linux/ext4 Gate 未关闭。
