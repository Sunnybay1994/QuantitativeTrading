# M3 黄金验收 fixture

这组 CSV 是人工可复算的验收真值，不是生产数据。所有日期均为虚构的 SH/SZ 开市日；周末未列入
`calendar.csv`。

统一语义：

- 信号日 `as_of = 2026-01-05`；
- entry 是下一开市日 `2026-01-06` 的 open；
- horizon=5 的 exit 是第 5 个未来开市日 `2026-01-12` 的 close；
- horizon=10 的 exit 是第 10 个未来开市日 `2026-01-19` 的 close；
- relative return = stock raw return - benchmark return；
- `000004.SZ` 缺少 entry 日行情，因此不能生成标签，禁止填价；
- `000003.SZ` 到 2026-01-12 才进入股票池，因此在 2026-01-05 的 PIT universe 中不合格；
- `000002.SZ` 在信号日仍合格，即使之后退出，不能利用未来退出事实删除已有训练样本。

文件：

| 文件 | 用途 |
|---|---|
| `calendar.csv` | D2 交易日 fold/embargo |
| `membership.csv` | D1/D4/D6 PIT 资格 |
| `bars.csv` | D3 股票标签，D4 staging |
| `benchmark_bars.csv` | D3 同区间基准收益 |
| `expected_labels.csv` | D3 精确真值 |
| `predictions.csv` | D5/D6 排序、覆盖率和资格过滤 |
| `eligibility_2026-01-05.csv` | D6 当日资格，不允许读取未来成员状态 |
| `expected_targets.csv` | D6 top_k=2、cash_buffer=0.1 真值 |
| `expected_folds.csv` | D2 train=4/valid=2/test=2/step=2/embargo=1 真值 |

数值手算：

- Benchmark h5 = `105/100-1 = 0.05`；h10 = `110/100-1 = 0.10`。
- `000001.SZ` h5 = `11/10-1 = 0.10`，relative=`0.05`；h10=`0.20-0.10=0.10`。
- `000002.SZ` h5 = `19/20-1 = -0.05`，relative=`-0.10`；h10=`-0.10-0.10=-0.20`。
- `000003.SZ` h5 = `31.5/30-1 = 0.05`，relative=`0`；h10=`-0.01-0.10=-0.11`。

读取 CSV 后应显式解析日期，不依赖本地时区。验收比较 label 使用绝对误差 `1e-10`；预测复现使用
`1e-12`。
