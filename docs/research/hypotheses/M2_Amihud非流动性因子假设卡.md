# M2 Amihud 非流动性因子假设卡

> 状态：真实不可变运行已完成，结论 `REJECTED`
> 最高结论：`RESEARCH_ONLY` / `REJECTED`
> 配置 SSOT：`configs/research/m2_amihud_illiquidity.toml`
> 结果：[M2 Amihud 非流动性因子研究结果](M2_Amihud非流动性因子研究结果.md)

## 1. 可证伪命题

月内单位成交额对应的价格变动越大，股票越不易交易。经典流动性溢价命题预期较高的 Amihud
非流动性对应较高的未来横截面收益，因此本轮预注册方向为 `+1`。该方向不是根据本项目样本挑选；任一
walk-forward fold 的 validation 选择出相反方向，因子即不得通过方向门禁。

Amihud 原始研究把日度绝对收益与美元成交额之比解释为粗粒度价格冲击代理，并报告预期收益与非流动性
正相关。它同时明确该指标不等价于价差、逐笔冲击或信息交易概率等更细的微观结构指标。因此本项目只把它
作为日频证伪候选，不把它解释为可执行容量模型。参考：[Amihud (2002), Journal of Financial Markets,
DOI 10.1016/S1386-4181(01)00024-6](https://doi.org/10.1016/S1386-4181(01)00024-6)。

## 2. 冻结口径

- 输入：冻结 clean `Bar1dSchema`，其中 `amount` 单位为 CNY；
- 日收益：相邻交易所 session 的 `close × adj_factor` 简单收益；证券缺失中间 session 时，跨缺口收益不参与；
- 日度值：`abs(adjusted_return) / (amount_CNY / 1_000_000)`，`amount <= 0` 为无效；
- 月度值：完整日历月内有效日度值均值，至少 15 个有效日，否则为 null；
- 信号：已证明闭合的日历月最后一个交易 session 收盘后可知；截断的最后月份不产生信号；
- IC 标签：固定 1/5/20 个 session 的 `next-open → later-open`；
- 组合标签：本月信号的下一交易 session 开盘建仓，下月信号的下一交易 session 开盘退出；
- 组合输出：只生成 `target_weight` 诊断，不自报成交，不进入 PAPER。

公式、门槛和成本参数以版本化配置及 `quant.factors.liquidity` 为准；本文不作为第二套数值 SSOT。

## 3. 预注册控制与门禁

- controls：现有经典价量、规模、`daily_basic` 价值代理，以及自由流通换手水平/异常；
- coverage：每个信号日不少于 100 个有效证券，所有信号日 coverage 中位数不低于 80%；
- redundancy：与任一预注册 control 的中位绝对横截面 RankCorr 必须严格小于 0.80；等于 0.80 也拒绝；
- walk-forward：沿用配置中的三个时间顺序 folds，不随机拆分；月频 IC 的 Newey-West lag 固定为 1；
- 成本：固定 0.5/1/2 倍 A 股成本压力，2 倍成本后不为正则拒绝；
- 决策：即使全部通过，仍只记为 `RESEARCH_ONLY`，等待 post-freeze forward 与人工 admission。

## 4. 关键反例

1. 复权前后等价价格路径必须产生相同因子；
2. 停牌造成的跨 session 跳跃不得伪装成普通一日收益；
3. `amount = 0` 不得用 epsilon 替代；
4. 最后一个未闭合月份不得进入样本；
5. 输入行序改变不得改变结果；重复证券—日期键必须拒绝；
6. coverage、方向或冗余任一门禁失败时，其他指标再好也只能 `REJECTED`。

## 5. 运行与结论记录

真实运行必须由同一个 frozen bar snapshot 和 frozen daily-basic snapshot 生成不可覆盖目录及 `run.json`。
运行前不预填 run id、收益或结论。完成后只在独立研究结果文档中链接 run 路径并记录通过/否证原因。
