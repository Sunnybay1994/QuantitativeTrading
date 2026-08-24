# M2 MAX 彩票偏好因子假设卡

> 状态：历史真实不可变运行已完成；R15 纠偏重放仅完成开发检查，尚未启动真实 run
> 最高结论：`RESEARCH_ONLY` / `REJECTED`
> trial budget：1
> 配置 SSOT：`configs/research/m2_classic_daily_factors_fifth_batch.toml`
> 结果文档：[M2 MAX 彩票偏好因子研究结果](M2_MAX彩票偏好因子研究结果.md)
> immutable run id：`10dea14f1fcbbbeb78871cddb7b00cd06d77cf005c3a776c4713f5a4f4129bb3`
> R15 约束：`trial_delta=0`；历史 run 保持 immutable/HOLD，R15 结果文档待唯一真实 run 后由领域经理创建
> R15 主配置 raw payload SHA-256：`860ca0ef600dd4de107f5e60dc8593cbb03ca6c7a3cac0cad0adf2d56a778c9f`；
> 任一配置字节漂移均在成本绑定、数据/snapshot 读取或 artifact 创建前 STOP，版本化配置仍是参数 SSOT

## 1. 可证伪命题与固定方向

本轮只检验一个候选 `max_daily_return_20`：过去 20 个严格连续 exchange sessions 中，单日复权收盘
简单收益的最大值越大，证券越具有“彩票式”极端正收益特征，随后横截面收益越弱。因此经济方向在看到
validation/test 结果前固定为 `-1`，即低 MAX 得分更高。validation 只负责检验该方向是否成立，不能把策略
翻成高 MAX 多头；任一 validation fold 的原始 RankIC 方向不是 `-1`，整个候选即 `REJECTED`。

Bali、Cakici 与 Whitelaw 发现，过去一个月最大单日收益与后续收益呈显著负相关，并把它解释为投资者对
彩票式收益的偏好。Gao、Han 与 Xiong 在中国股票市场报告了同方向的 MAX effect：高 MAX 减低 MAX 的
零成本策略在全样本显著亏损。两篇论文是方向先验，不是本项目样本有效性的保证；本轮仍必须在冻结数据、
next-open 标签、walk-forward 和成本压力下独立证伪。

主要参考：

- [Bali, Cakici and Whitelaw (2011), *Maxing Out: Stocks as Lotteries and the Cross-Section of Expected Returns*, Journal of Financial Economics 99(2), 427–446](https://doi.org/10.1016/j.jfineco.2010.08.014)
- [作者公开论文 PDF](https://pages.stern.nyu.edu/~rwhitela/papers/max%20jfe.pdf)
- [Gao, Han and Xiong (2021), *Loss from the chasing of MAX stocks: Evidence from China*, The North American Journal of Economics and Finance 58, 101475](https://doi.org/10.1016/j.najef.2021.101475)

## 2. 冻结公式与数据边界

对证券 `i` 和 exchange session `s`：

`P(i,s) = close(i,s) × adj_factor(i,s)`

`r(i,s) = P(i,s) / P(i,s-1) - 1`

`MAX20(i,t) = max(r(i,t-19), ..., r(i,t))`

- 因子在 `t` 需要 `t-20..t` 共 21 个严格连续 session 的价格，才能形成 20 个收益；
- 任一 session 缺失、价格/复权因子非正或非有限、乘法/除法溢出，都不得跨缺口计算；
- `max` 是**有符号简单收益的最大值**，不是最大绝对收益。若窗口收益为 `+5%` 与 `-20%`，MAX 为
  `+5%`；若全部为负，则取最接近 0 的最大值；
- 股票池继续只由 2019 冻结期的成交额与观测数选择，不用研究期收益换股；
- 输入 clean snapshot 固定为配置中的不可变 snapshot id。

论文使用“过去一个月”；本项目预注册为固定 20 exchange sessions，以便与既有 20-session 调仓、标签和
成本诊断对齐。该参数不因结果而改成 5、21 或 30。

## 3. 与 Qlib Alpha158 `MAX20` 的边界

用户资料 `docs/quant_factor_research_v2/02_Qlib_Alpha158_完整清单与分析.md` 中的 Qlib `MAX20` 是
`Max(high,20) / close`，属于价格高点相对当前价；本轮因子是过去 20 个**日收益**的最大值。两者公式、
单位和机制均不同，因此生产列名使用 `max_daily_return_20`，不得复用 `alpha158_max20` 或声称同式。

## 4. 时间、walk-forward 与组合诊断

- `as_of`：session `t` 收盘后；最早成交为下一 exchange session 开盘；
- 标签：固定 1/5/20 session 的 `open(t+1+h) / open(t+1) - 1`；
- 三个时间顺序 folds；test 不参与方向、窗口、阈值或 controls 的选择；
- 固定方向 `-1`，每 20 个预注册 session 调仓，取低 MAX 方向得分最高的 50 只并输出等权
  `target_weight`；
- 成本压力固定 0.5/1/2 倍；组合仍是 research diagnostics，不是 formal 回放或 PAPER admission；
- 实际 target 日期必须逐 fold 精确等于与因子无关的预注册日期，因子缺失不得顺延。

## 5. Controls 与 fail-closed 门禁

冗余 controls 固定为已有 16 个第一至第四批经典价量因子，再加 `liquidity_20`。研究期逐日横截面
RankCorr 的最大中位绝对值必须严格 `< 0.80`；等于 0.80 也失败。没有历史 PIT 行业，不做伪行业中性。

候选必须同时满足：

1. 每个预注册调仓日至少 100 个有效证券，全部信号日 coverage 中位数至少 80%；
2. 三个 validation folds 的原始方向都精确为 `-1`，实际组合方向始终固定为 `-1`；
3. 20-session 方向化 test RankIC 跨 fold 均值至少 0.01，至少 2/3 folds 为正；
4. 最大中位绝对 RankCorr 严格 `< 0.80`；
5. 2 倍成本后的跨 fold 链式收益严格为正；
6. 实际 target 日期逐 fold 与预注册集合完全一致。
7. primary 仅消费 `test`/`horizon=20` 的固定五组：每个预注册 signal date 必须有完整且唯一的
   group 1..5、`coverage=PASS`、满足既有 minimum-symbol 合同且收益 finite；score 为
   `factor * direction` 且 group 按 score 升序，固定方向 `-1` 时 group1 为高 MAX、group5 为低 MAX，
   要求 `group1 <= group2 <= group3 <= group4 <= group5`，至少 2/3 folds 且 pooled 通过。

任一失败即 `REJECTED`；全部通过也最高为 `RESEARCH_ONLY`。若历史初筛通过，进入 forward 前还必须以
`daily_basic` 增补 `log_total_market_value` 和 turnover 的二阶段增量控制，不能直接申请
`PAPER_CANDIDATE`。

## 6. 关键反例

1. 20 个价格只能形成 19 个收益，末行必须为 null；21 个连续价格才可形成第一个值；
2. 窗内删一个 exchange session 后，受影响窗口必须为 null，不能跨缺口桥接；
3. `+5%/-20%` 返回 `+5%`，全负窗口返回最不负值，不能取绝对值最大者；
4. 拆并股改变 raw close、但 `close × adj_factor` 路径相同时结果不变；
5. 修改 `t+1` 或更晚价格不得影响 `t`，输入行序也不得影响结果；
6. 重复证券—日期、日历外日期、NaN/Inf 必须 fail closed；
7. coverage 79.999%、冗余恰为 0.80、调仓日平移一天或任一 validation fold 方向为 `+1`，均须
   `REJECTED`。

## 7. 真实运行与停止条件

资源槽内只允许一次不可覆盖真实 run，不得看到结果后调方向、窗口、阈值或 controls 重跑。运行必须绑定
snapshot、配置与代码摘要，并保留 `run.json`、targets、IC、分组收益、成本 NAV、coverage、冗余和调仓日
对账。按可取得程度记录 wall、CPU、峰值 RSS 和面板规模；不为补性能指标重跑。

财务采集若在已启动的唯一 run 中途完成，不中断本 run；本包结束后，PIT 财务质量研究立即优先于新增的
bar-only 因子包。

R15 纠偏重放只关闭 classic MAX 的 same-payload config/cost semantic identity、标准成本 input 和上述
primary monotonicity admission gate；不关闭 PIT 对称 redundancy coverage、audit-v4、R3 或任何交易准入，
也不改写历史 run。真实 run 尚未执行，因此本卡不记录 R15 结果或新的 run id。
