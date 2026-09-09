# PAPER 月度净值与回测对照

2026-09-09：现有 S0 历史演练的 42 个共同交易日已生成 3 个月的对照表；7 月 −1.6561%、8 月 +1.2728%、9 月截至 8 日 −1.4699%。这份示例是历史演练；实际前向账户有净值后，用其最新 `nav.csv` 重跑。

## 运行

Windows Miniforge，项目根目录下：

```powershell
$env:PYTHONPATH = 'F:/AI_Coding/QuantitativeTrading/src'
$benchmark = 'artifacts/research/runs/894eb1818f1218f4d17c2b89a99e44d044b79ed1274727b786d25611261e6e03/nav.parquet'
D:/Miniforge3/python.exe -m quant.reporting.paper_monthly --ledger artifacts/paper/rehearsal/2026-09-08/nav.csv --benchmark $benchmark --benchmark-filter fold=3 --benchmark-filter period=test --benchmark-filter comparison=s0 --benchmark-filter cost_multiplier=1.0 --mode rehearsal --benchmark-note 'S0同池；演练比例滑点0.1%，回测每股0.001元滑点，不能用差异归因执行质量。' --output artifacts/paper_monthly/my_rehearsal_report
```

`--ledger` 接受一个已有账本快照的完整累计 NAV CSV；`--benchmark` 接受 CSV/Parquet。两源须有 `date`、`unit_nav`。多个策略、折、时期、成本档必须用可重复的 `--ledger-filter key=value` / `--benchmark-filter key=value` 选成一条序列。输出目录必须尚不存在。

实际前向记录用 `--mode paper`。空账本会提示尚无净值，不创建虚拟记录。遇到无共同日期，等同期回测和前向数据齐备后再运行。不同起始日的回测应重新生成同起始日账户，不能截掉首日后手工归一。

## 计算与输出

- `monthly.csv`：共同日期数量、未配对日期数、实际起止日、收益基准日期、月末双方原始净值、月收益及差异百分点。
- `common_nav.csv`：仅共同日期的原始净值，以及按比较起点资本归一的双方净值和净值差。
- `report.md`：可阅读的月报，记录输入路径、筛选条件、初始净值和成本说明。

首期收益分母为成交前初始净值（默认 1，可由 `--paper-initial-nav` / `--benchmark-initial-nav` 指定）；因此包含首日费用和首日价格损益。后续期收益为本月最后共同日净值 / 上月最后共同日净值 − 1，不填充缺失日期。起始收益区间不一致或整月无共同日期时拒绝合并，防止跨月收益被冠以单月名称。

首尾月保守标为部分月；中间月份以两源观测日期并集判断配对是否完整，不推断交易所节假日日历。`base_date` 为空表示首期使用初始资本。若缺失月末日期，报告会标出受影响的收益区间边界。

## 已有示例与抽样

三个成本档均复用已有 B4 回测 S0 第三测试折，没有重跑或改动账本：

- [0.5× 成本对照](../../artifacts/paper_monthly/rehearsal_20260909_v2_cost0.5/report.md)
- [1× 成本对照](../../artifacts/paper_monthly/rehearsal_20260909_v2_cost1.0/report.md)
- [2× 成本对照](../../artifacts/paper_monthly/rehearsal_20260909_v2_cost2.0/report.md)

1× 对照，月差异依次 +0.01675 / +0.00149 / +0.00169 个百分点。抽样：7 月 PAPER 末净值 0.9834393672 / 初始 1 − 1 = −1.656063%；8 月 0.9959564697 / 0.9834393672 − 1 = +1.272788%。首日净值 0.9841961672 保留，未重置为 1。

关键限制：演练为比例滑点 0.1%，B4 回测为每股 0.001 元滑点；三档只改变回测成本，PAPER 是固定账本，所以本例检验报表能力，不能把小差异归因为执行质量。

定向验证：`pytest tests/unit/test_paper_monthly.py -q --basetemp artifacts/tmp/paper_monthly_tests_<new_name>`；Ruff 检查该模块及测试；mypy `--follow-imports=skip` 检查同两文件。
