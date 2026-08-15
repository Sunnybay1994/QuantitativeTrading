# M2 MAX 规模与换手二阶段控制研究结果

> 结论：`REJECTED`
> 运行日期：2026-08-16
> 配置：`configs/research/m2_max_daily_basic_controls.toml`
> immutable run id：`30326191600e84cc0c94f9f040ecd5ed0ff9a944e6ed02a183ba5169d7a8e2cf`

## 1. 结论先行

本轮是 canonical MAX 同一假设的确认性控制，不是新候选。`max_daily_return_20` 在同日总市值与自由流通
换手率的横截面 average-rank OLS 控制后，残差信号仍有稳定的方向化 RankIC：三个 test folds 均为正，
平均值为 `0.045705`。固定 `-1` 方向、coverage、预注册调仓日和全部 OLS 数值门禁也都通过。

但预注册的 2 倍成本门禁没有通过：三折链式收益为 `-5.0079%`。因此唯一真实 run 按运行前合同落为
`REJECTED`，没有事后修改方向、阈值、窗口或数值容差，也没有第二次真实 run。原始 MAX run 的历史
`RESEARCH_ONLY` 标签仍是其自身不可变记录，但加入本轮确认性证据后，该假设不能向 S2、
`PAPER_CANDIDATE` 或 PAPER 推进。

机器产物当前暂存于短生命周期 worktree：

`artifacts/research/runs/30326191600e84cc0c94f9f040ecd5ed0ff9a944e6ed02a183ba5169d7a8e2cf`

目录含 15 个文件、307,425 bytes；`run.json` SHA256 为
`339C8D44360816FBC827DE9AA77569BAAF513F1DFD89B4AF7BAB9EB7F8E9D3EA`，绑定两个 clean snapshot、
配置、代码和 14 个输出摘要。JSON/报告/目录清单中没有 worktree 绝对路径。canonical retained 仍由
统筹按 no-clobber、逐文件 size/SHA256 验真流程处置，本任务不移动、复制或重签产物。

## 2. 数据、公式与时间合同

- raw MAX 来源是 freshly verified canonical run `10dea14f…129bb3`；其候选池、folds、成本和
  close→next-open 时间语义与本轮逐项一致；
- bar snapshot：`b79a7b5e…1089d2`，输入股票日线 17,766,134 行；
- daily-basic snapshot：`e97c0e9c…b4c03c`，输入 16,949,896 行；
- 冻结候选池为 2019 年流动性 top 800，研究面板 1,230,269 行；
- 每个 `as_of=t close` 横截面用含截距 OLS 将 raw MAX 的 average rank 对
  `log(total_market_value)` 与 `turnover_rate_free` 的 average rank 残差化；
- 唯一信号是 `max_daily_return_20_size_turnover_residual`，经济方向始终为 `-1`；
- 标签与诊断组合最早使用下一 exchange session 开盘；每 20 个预注册 session 调仓，Top-50 等权
  `target_weight`，walk-forward 和 0.5/1/2 倍成本均沿用冻结合同；
- trial budget 精确为 1，本轮不把 raw MAX、规模或换手相关性误作新候选冗余门禁。

## 3. 门禁证据

| 门禁 | 实际证据 | 结论 |
|---|---:|---|
| validation 原始方向全部为 `-1` | 3/3 folds | 通过 |
| 平均方向化 test RankIC `>= 0.01` | 0.045705 | 通过 |
| 正 test folds 至少 2/3 | 3/3 | 通过 |
| 全部研究日 OLS 数值闭包 | 1,603/1,603 | 通过 |
| 全部信号日 coverage 中位数 `>= 80%` | 99.3548% | 通过 |
| 每个预注册调仓日至少 100 个有效证券 | 最小 733 | 通过 |
| 实际调仓日逐 fold 精确一致 | 12/12、12/12、7/7 | 通过 |
| 1 倍成本后跨 fold 链式收益 | +1.8489% | 通过 |
| 2 倍成本后跨 fold 链式收益严格 `> 0` | **-5.0079%** | **失败** |

三个 test folds 的方向化 RankIC 分别为 `0.033864 / 0.040846 / 0.062404`。2 倍成本下各 fold 组合收益
分别为 `-19.6971% / +23.0587% / -3.8734%`；1 倍成本下分别为
`-17.4607% / +26.3320% / -2.3253%`。这说明控制后横截面排序仍有统计信号，但收益仍高度依赖 2024
test fold，并且在冻结的压力成本下不能覆盖交易摩擦。

OLS 共覆盖 1,603 个研究日，最少完整横截面为 733；最大 condition number 为 `4.527634`，最大
normal-equation orthogonality error 为 `1.8987e-15`，均远在预注册的 `1,000,000.0` 与 `1e-10`
边界内。没有日期通过填充、伪逆、ridge 或删控制项获得结果。

解释性每日 RankCorr 汇总为：残差对 raw MAX 的中位绝对值 `0.817659`，对规模 `0.009463`，对自由流通
换手 `0.045092`。raw MAX 相关性较高只说明条件信号仍保留大量原始排序，不是本轮的自相关拒绝项；真正的
否决来自事前冻结的 2 倍成本门禁。

## 4. 性能与开发反馈

唯一真实 run 使用 Windows Miniforge、CPU8—11 affinity `0xF00`、BelowNormal，Polars/数值线程不超过
2，且没有第二个研究 Python 实例：

- 单调 wall time：120.289 秒；
- 完整进程 CPU time：65.156 秒；
- `PeakWorkingSet64`：1,546,899,456 bytes，约 1.44 GiB；
- 数据规模：股票日线 17,766,134 行、daily-basic 16,949,896 行、面板 1,230,269 行、1,603 个有效
  研究日、31 个预注册调仓日；
- snapshot verify / query / factor / walk-forward / publish 分段耗时和可靠进程 I/O bytes 仍未捕获。

正常开发检查为 focused `25 passed`，Ruff、mypy（2 个源文件）、py_compile、TOML 解析和冻结配置校验
全部通过。由于没有阶段 profile，不能把 120 秒直接归因于 I/O、OLS 或发布，也不据此增加线程、GPU 或
缓存。本次 immutable run 不为补性能指标而重跑。

## 5. 后续处置

1. 由统筹按 no-clobber 与逐文件 SHA256 流程把本 run 保留到项目级 canonical research runs；
2. 不向 S2 提交 admission，不生成 `PAPER_CANDIDATE`，不建立 PAPER 账户或订单；
3. 不用原始 MAX 的历史 `RESEARCH_ONLY` 覆盖本轮失败，也不在相同历史窗口调阈值后重测；
4. 财务 snapshot READY 后立即回到已冻结的 PIT 财务质量研究，优先验证与价格量能机制更正交的证据；
5. 若未来重启 MAX 研究，只能作为全新预注册假设，使用 post-freeze forward、正式市场事件回放及独立
   admission 证据，不能把本轮历史样本继续用作调参集。
