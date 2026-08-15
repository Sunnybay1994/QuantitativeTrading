# M2 MAX 规模与换手二阶段控制研究结果

> 结论：`REJECTED`
> 运行日期：2026-08-16
> 配置：`configs/research/m2_max_daily_basic_controls.toml`
> immutable run id：`30326191600e84cc0c94f9f040ecd5ed0ff9a944e6ed02a183ba5169d7a8e2cf`

> **TARGET R11 INVALID ECONOMIC EVIDENCE（2026-08-16）**：immutable run 与 `REJECTED` 状态保持不变，
> 不回写、不升级。RankIC、固定方向、coverage、调仓日和 OLS 数值闭包只保留为描述线索；targets、NAV、
> 组合收益、换手及 0.5x/1x/2x 成本字段无效。由于本 run 的拒绝只由受影响的 2x 成本腿触发，
> `-5.0079%` 不得继续表述为有效经济证伪；这也不授权重跑、翻案或恢复原始 MAX 的推进资格。当前处置见
> [M2 执行路线图](../roadmaps/M2_策略与因子库并行建设路线图.md)。

## 1. 结论先行

本轮是 canonical MAX 同一假设的确认性控制，不是新候选。`max_daily_return_20` 在同日总市值与自由流通
换手率的横截面 average-rank OLS 控制后，残差信号仍有稳定的方向化 RankIC：三个 test folds 均为正，
平均值为 `0.045705`。固定 `-1` 方向、coverage、预注册调仓日和全部 OLS 数值门禁也都通过。

历史产物按当时预注册合同因 2 倍成本腿 `-5.0079%` 落为 `REJECTED`，该不可变状态继续保留。TARGET R11
现已确认该成本腿不是有效经济证据，因此本 run 不能再用于证明 MAX 在规模/换手控制后失效；原始 MAX
同样继续 HOLD，二者均不得进入 forward、S2、`PAPER_CANDIDATE` 或 PAPER，也不得为求改变结论而批量重跑。

机器产物已由统筹按 no-clobber、逐文件 size/SHA256 验真后保留到项目级 canonical
`artifacts/research/runs/30326191600e84cc0c94f9f040ecd5ed0ff9a944e6ed02a183ba5169d7a8e2cf/`；
来源 worktree/branch 已 archive-first 退休。本页只记录历史 identity，不再描述来源 worktree 的当前状态。

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

下表保留历史产物原值用于审计；涉及目标、组合和成本的“通过/失败”均不是 R11 后可用的经济门禁证据。

| 门禁 | 实际证据 | 结论 |
|---|---:|---|
| validation 原始方向全部为 `-1` | 3/3 folds | 通过 |
| 平均方向化 test RankIC `>= 0.01` | 0.045705 | 通过 |
| 正 test folds 至少 2/3 | 3/3 | 通过 |
| 全部研究日 OLS 数值闭包 | 1,603/1,603 | 通过 |
| 全部信号日 coverage 中位数 `>= 80%` | 99.3548% | 通过 |
| 每个预注册调仓日至少 100 个有效证券 | 最小 733 | 通过 |
| 实际调仓日逐 fold 精确一致 | 12/12、12/12、7/7 | 通过 |
| 1 倍成本后跨 fold 链式收益 | +1.8489% | 历史记录；R11 后无效 |
| 2 倍成本后跨 fold 链式收益严格 `> 0` | **-5.0079%** | **历史记录；R11 后无效** |

三个 test folds 的方向化 RankIC 分别为 `0.033864 / 0.040846 / 0.062404`。2 倍成本下各 fold 组合收益
分别为 `-19.6971% / +23.0587% / -3.8734%`；1 倍成本下分别为
`-17.4607% / +26.3320% / -2.3253%`。这说明控制后横截面排序仍有统计信号，但收益仍高度依赖 2024
test fold，并且在冻结的压力成本下不能覆盖交易摩擦。

OLS 共覆盖 1,603 个研究日，最少完整横截面为 733；最大 condition number 为 `4.527634`，最大
normal-equation orthogonality error 为 `1.8987e-15`，均远在预注册的 `1,000,000.0` 与 `1e-10`
边界内。没有日期通过填充、伪逆、ridge 或删控制项获得结果。

解释性每日 RankCorr 汇总为：残差对 raw MAX 的中位绝对值 `0.817659`，对规模 `0.009463`，对自由流通
换手 `0.045092`。raw MAX 相关性较高只说明条件信号仍保留大量原始排序，不是本轮的自相关拒绝项；运行
当时的拒绝由 2 倍成本门禁触发，但该经济腿在 R11 后无效，不能再作为确认性证伪。

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

## 5. 当前处置

1. canonical run 与 `REJECTED` 状态保持不可变，不重签、不覆盖；
2. 2x 成本腿标记为 invalid economic evidence，不用于确认性证伪；
3. 原始 MAX 继续 HOLD，本控制 run 也不得进入 forward、S2/admission、`PAPER_CANDIDATE` 或 PAPER；
4. 不在相同历史窗口重跑或调参；未来若研究 MAX，只能另立全新预注册假设并服从当前 M2 执行 SSOT。
