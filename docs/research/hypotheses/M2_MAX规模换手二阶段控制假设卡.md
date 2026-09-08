# M2 MAX 规模与换手二阶段控制假设卡

> 状态：预注册已执行；唯一真实 run 为 `REJECTED`
> 结论上限：`RESEARCH_ONLY`
> trial budget：1
> 配置：`configs/research/m2_max_daily_basic_controls.toml`
> 结果：[M2 MAX 规模与换手二阶段控制研究结果](M2_MAX规模换手二阶段控制研究结果.md)

## 1. 要回答的问题

首轮 `max_daily_return_20` 的不可变 run
`10dea14f1fcbbbeb78871cddb7b00cd06d77cf005c3a776c4713f5a4f4129bb3`
通过历史初筛，但这仍可能只是规模或交易活跃度暴露。本轮只检验一个确认性问题：在每个 `as_of` 收盘时点，
用同日已知的总市值和自由流通换手率做横截面控制后，MAX 的剩余部分是否仍具有固定为 `-1` 的下一开盘收益
关系。

本轮不是新候选，不重新搜索 MAX 窗口、方向、调仓频率或阈值，也不因控制后结果不理想而回看原始 MAX
重新选参。即使全部门禁通过，结论最高仍是 `RESEARCH_ONLY`，不得进入 S2、生成 `PAPER_CANDIDATE`
或启动 PAPER。

## 2. 冻结输入与时间语义

- 原始 MAX 必须来自 freshly verified canonical run `10dea14f…129bb3`；其 `run.json`、13 个输出、候选池、
  walk-forward folds、成本倍数和时间语义均须通过既有 immutable-run verifier。
- bar snapshot 固定为 `b79a7b…1089d2`，研究窗口固定为 2020-01-01 至 2026-08-13；原始 run 与本轮的
  bar manifest、2019 冻结流动性 top 800、候选证券和三个 folds 必须精确一致。
- `daily_basic` snapshot 固定为 `e97c0e9c…b4c03c`，运行时参数必须精确相等；`total_market_value` 和
  `turnover_rate_free` 只在同一 `trade_date` 收盘后使用，不前填、不后填、不跨日期替代。
- 信号 `as_of=t close`；最早执行仍是 `t+1` exchange-session open。1/5/20 标签、每 20 session
  调仓、Top-50 等权 `target_weight` 和 0.5/1/2 倍成本沿用既有 runner。

## 3. 冻结公式

对证券 `i`、交易日 `t`：

1. `MAX(i,t)` 沿用首轮公式：20 个严格连续 exchange-session 复权收盘简单收益的最大有符号值；
2. `SIZE(i,t) = log(total_market_value(i,t))`，仅正且有限的市值有效；
3. `TURN(i,t) = turnover_rate_free(i,t)`，仅有限值有效；
4. 在每个 `t` 的完整样本上分别对 `MAX`、`SIZE`、`TURN` 作升序 average rank；
5. 以含截距横截面 OLS 估计
   `rank(MAX) = alpha + beta_size*rank(SIZE) + beta_turn*rank(TURN) + epsilon`；
6. 唯一候选因子为残差 `epsilon`，列名
   `max_daily_return_20_size_turnover_residual`。高残差代表在相同规模和换手水平下仍更强的彩票偏好，
   因而经济方向固定为 `-1`（低残差优先）。

横截面 rank 使市值单位与换手百分比单位不影响估计。本项目采用 rank-OLS 是为了得到可直接进入现有
next-open 研究链的条件信号；它不是对文献中双重排序或 Fama—MacBeth 规格的逐字复刻。

## 4. 数值闭包（运行前冻结）

以下值全部写入版本化 TOML，并由定向测试锁定：

| 项目 | 冻结值 |
|---|---:|
| rank tie method | `average` |
| regression | `cross_sectional_rank_ols_with_intercept` |
| 每日最少完整样本 | 100 |
| 奇异判定 | centered 2×2 Gram matrix 的最小特征值必须严格大于 0 |
| 最大 condition number | `1,000,000.0`（等号通过） |
| normal-equation orthogonality tolerance | `1e-10`（等号通过） |

任一控制缺失/非有限、设计奇异、condition 超限、残差方差为零或正交误差超限时，该日残差为 null；不得
改用伪逆、ridge、删控制项或静默放宽阈值。正交误差取残差均值绝对值、残差与两个中心化控制的归一化内积
绝对值三者的最大值。

## 5. 预注册门禁

本轮先沿用既有通用研究门禁，再增加控制专属门禁：

1. 20-session 方向化 mean test RankIC `>= 0.01`；
2. 至少 2/3 test folds 的方向化 RankIC 为正；
3. 2 倍成本下三折链式总收益严格 `> 0`；
4. 实际组合方向始终为 `-1`，且三个 validation folds 的原始方向全部为 `-1`；
5. 每个预注册调仓日至少 100 个有效残差；全部研究日 coverage 中位数 `>= 0.80`；
6. 每 fold 实际 `target_weight.as_of` 必须与因子值无关的 20-session 预注册调仓日逐项相等，不允许顺延；
7. 研究窗口内每个日期的 OLS 数值闭包均通过。

残差与 raw MAX、规模、换手的每日 RankCorr 仍落盘解释，但不再作为 `<0.80` 的自相关拒绝门禁：残差本来
就是同一 MAX 假设的控制后表示，以与 raw MAX 的相关性拒绝它会把“同一假设的确认控制”误判成新因子
冗余。任何其他门禁失败则最终结论为 `REJECTED`。

## 6. 反例与不可变性要求

- 同日只有 99 个完整样本时，该日必须无有效残差；100 个才可进入回归；
- 两个控制完全共线、最小特征值不正或 condition 超限时必须 fail closed；
- condition 恰等于上限、正交误差恰等于 tolerance 时允许通过，任意更大值拒绝；
- 改动 `t+1` 或未来的 daily-basic/bar 行不得改变 `t` 的因子；输入行顺序不得改变结果；
- duplicate symbol-date、out-of-calendar 或非有限输入必须拒绝；
- validation 任一 fold 的原始方向不是 `-1`、coverage 低于 80%、调仓日少/多/顺延一天都必须拒绝；
- fresh raw run 缺失、被改写、run id 不符或与本轮 bar snapshot/候选池/folds/时间语义不一致时，不得开始
  研究计算，也不得发布半成品。

## 7. 证据边界与参考

MAX 的经济动机来自 Bali、Cakici 与 Whitelaw 对极端正收益与后续收益关系的研究；原论文同时报告了控制
规模、账面市值比、动量、流动性等特征后的结果。本轮只将其中“需要验证 MAX 是否独立于常见暴露”的思想
转成项目内可执行的日度 rank-OLS 控制，不声称复制其完整实证设计。

- Bali, T. G., Cakici, N., & Whitelaw, R. F. (2011), *Maxing Out: Stocks as Lotteries and the Cross-Section of Expected Returns*, Journal of Financial Economics, 99(2), 427–446. DOI: <https://doi.org/10.1016/j.jfineco.2010.08.014>
- 作者公开稿：<https://pages.stern.nyu.edu/~rwhitela/papers/max%20jfe11.pdf>

当前数据仍缺历史动态 ST、行业、完整市场事件与正式可交易性，因此通过控制也只是历史研究诊断；后续仍需
post-freeze forward、统一市场事件回放、S2 只读 admission 和人工决定。

资源槽释放且 financial snapshot 仍未 READY 时，唯一真实 run 使用下列接口；canonical MAX 必须是项目级
已保留目录，不能复制、重签或改写：

```powershell
$projectRoot = (Resolve-Path .).Path
$sharedRoot = 'F:\AI_Coding\QuantitativeTrading'
python -m quant.research.run_daily_value_factors `
  --config configs/research/m2_max_daily_basic_controls.toml `
  --daily-basic-snapshot-id e97c0e9c82c445bbc9b389e8e8504f61b0b67d2f789208f75625526c38b4c03c `
  --raw-max-run-root "$sharedRoot\artifacts\research\runs\10dea14f1fcbbbeb78871cddb7b00cd06d77cf005c3a776c4713f5a4f4129bb3" `
  --data-root "$sharedRoot\data" `
  --artifact-root artifacts `
  --project-root $projectRoot `
  --threads 2
```
