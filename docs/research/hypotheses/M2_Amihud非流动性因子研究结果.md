# M2 Amihud 非流动性因子研究结果

日期：2026-08-16
结论：`REJECTED`；没有策略候选，不生成 `PAPER_CANDIDATE`，不启动 PAPER

## 1. 可重放身份

- 不可覆盖 run：
  [`25c747ae9d608ab71aaa5a09034b6e0a5f14fa7c3c5209383964df6b7068329c`](../../artifacts/research/runs/25c747ae9d608ab71aaa5a09034b6e0a5f14fa7c3c5209383964df6b7068329c/run.json)；
- bar snapshot：`b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2`，
  17,766,134 条股票日线；
- daily-basic snapshot：`e97c0e9c82c445bbc9b389e8e8504f61b0b67d2f789208f75625526c38b4c03c`，
  16,949,896 条合格记录；
- 冻结股票池：2019 年流动性 Top 800；研究面板 60,581 行；
- `run.json` 绑定配置、代码 SHA-256、两份输入内容摘要和 11 个输出文件，首次运行 `reused=false`。

## 2. 冻结协议

- 完整日历月收盘后形成信号，最早在下一交易 session 开盘执行；
- 月内日度值为 `abs(adjusted_return) / (amount_CNY / 1_000_000)`，至少 15 个有效日；
- 1/5/20 session next-open 标签，三个时间顺序 walk-forward folds，月频 Newey-West lag=1；
- 组合只输出 `target_weight` 诊断，并报告 0.5x/1x/2x 成本压力；
- 每个信号日有效证券至少 100、coverage 中位数至少 80%，与任一预注册 control 的中位绝对
  RankCorr 必须严格小于 0.80。

## 3. 结果

| 指标 | 结果 | 门禁 |
|---|---:|---|
| 平均 test RankIC | -0.01023 | 未通过预注册正方向 |
| 正 RankIC folds | 1/3 | 未通过至少 2/3 |
| validation 方向 | `+1 / +1 / +1` | 与预注册 `+1` 一致 |
| 1x 串联诊断收益 | 67.17% | 仅诊断 |
| 2x 串联诊断收益 | 62.61% | 成本压力通过但不能覆盖其他失败 |
| 最大中位绝对 RankCorr | 0.8620 | 未通过 `< 0.80` |
| coverage 中位数 | 99.75% | 中位数通过 |
| 最低有效证券数 | 0 | 未通过逐信号日至少 100 |

该因子同时被 test 方向/折数、冗余和逐日 coverage 三项门禁否证。正的诊断组合收益不能替代这些
预注册门禁，也不能被解释为可执行容量或正式账户收益。

## 4. 2026 年 2 月覆盖缺口

冻结快照中，候选池在 2026 年 2 月只有 14 个交易 session（2 月 2 日至 2 月 27 日），10,458 条
bar 记录的 `amount` 均为正；同月 daily-basic 也有相同 14 个 session 和 10,458 条非空自由流通换手记录。
因此 2026-02-27 的 745 个 eligible symbols 全部因“月内至少 15 个有效日”的预注册规则返回 null，
而不是因为文件缺失、零成交额或供应商空值。

这是研究假设与真实 A 股日历的有效反例。当前 run 保持 `REJECTED`；不得在观察结果后把 15 改成 14
并覆盖本次结果。若未来研究“按当月全部开市日覆盖比例”的 v2 口径，必须另写假设卡、另发不可变 run，
并把新增试验计入 trial count。

## 5. 决策

1. 不把 Amihud v1 纳入组合或 PAPER admission；
2. 不在同一 holdout 上调整窗口、阈值或 control 集合；
3. 保留 run 和失败原因，后续 downside beta 包继续按独立预注册机制推进；
4. 如研究 v2，只能把它视为新假设，不能回写或替代本次 `REJECTED` 证据。
