# M3 G7F 开发示例三场景回测主 Agent 阶段验收报告

日期：2026-08-02

## 结论

G7F 开发示例三场景 BacktestArtifact 合同通过。G8/G9 的工程路径可消费 strict verified development
backtest bundle，但本结论不等同于正式 G7、正式 G1 Linux/ext4 Gate、真实数据性能或 M3 最终准入通过。

## 已实现

- `0p5x`、`1p0x`、`2p0x` 固定顺序、相同初始现金、相同 verified market facts 和同一基础费率表，分别创建
  独立账户并完整回放；没有复用 1× fills 或调用方自报 multiplier、schedule、metrics、digest。
- 倍数只缩放佣金率、最低佣金和滑点；法定印花税、过户费与历史生效区间保持不变。
- 每场景固定输出七张 schema 表、strict metrics 和 manifest；根目录固定输出有序三场景 metrics 与 bundle
  manifest。scenario manifest 精确覆盖七表及 metrics，不把自身纳入自身 hash。
- 指标实现覆盖组合/年化收益、prepend-1 最大回撤、`510300.SH` raw open-to-close benchmark、净超额与相对财富、
  target/realized turnover、费用与滑点分项、拒绝/未成交、现金占比、公司行动 posting、末日持仓和 1× 退出成本。
- verifier 从 verified inputs 重建 market facts，独立重跑三个账本，逐表、逐 metrics、逐 manifest 核对；目录树
  多文件、少文件、内容篡改、未知规则版本或 development/formal identity 混用均 fail-closed。
- backtest StageReceipt 固定 `WORK/work_key`，输入精确 21 个文件，输出递归精确 29 个文件；上游四张 receipt
  还须与 verified 对象记录的 SHA-256 一致。公共 receipt 层继续禁止同一物理 root 绑定多个 alias。
- 任务单残留 benchmark `H00300.CSI` 已同步为用户批准且配置/领域合同冻结的 `510300.SH`。

## 验证

Windows 原生 Miniforge：

```text
pytest tests/unit/test_m3_a_share_simulator.py
       tests/integration/test_m3_a_share_simulator_golden.py
       tests/unit/test_m3_a_share_reporting.py
       tests/integration/test_m3_a_share_reporting_receipt.py
18 passed in 251.46s
ruff check <G7E/G7F changed files>
All checks passed!
mypy <G7E/G7F source files>
Success: no issues found in 6 source files
```

WSL Miniforge base（源码在 `/mnt/f`，不是 ext4 Gate）：

```text
pytest <same G7E/G7F tests>
18 passed in 133.92s
ruff check <same G7E/G7F files>
All checks passed!
mypy <same G7E/G7F source files>
Success: no issues found in 6 source files
```

Pandera/Polars 产生已知弃用警告；Windows pytest cache 另有工作树 ACL 警告，均未改变测试结果。

## 剩余风险与下一步

- development public fixture 当前回测窗口只有两个 session；合同、身份、账本和 receipt 已闭包，但正式 G7
  仍须在真实 G1 release 上重跑完整 test window，并由真实数据验证停牌、公司行动、涨跌停和末日残仓分布。
- 当前开发 bundle 不具有 `VerifiedG1Release` 或 formal-gate-eligible 身份，G8/G9 只能据此开发编排、恢复、
  验真与失败语义，不能宣称正式 Gate 通过。
- 正式研究链已完成 G2C；G3A 工程验证完成后仍需先补 G8 ExperimentIdentity 正式前置，随后继续正式发布。
