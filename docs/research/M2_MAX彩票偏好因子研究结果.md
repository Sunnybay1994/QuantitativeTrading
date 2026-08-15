# M2 MAX 彩票偏好因子研究结果

> 结论：历史初筛 `RESEARCH_ONLY`
> 运行日期：2026-08-16
> 配置：`configs/research/m2_classic_daily_factors_fifth_batch.toml`
> immutable run id：`10dea14f1fcbbbeb78871cddb7b00cd06d77cf005c3a776c4713f5a4f4129bb3`

> **TARGET R11 HOLD（2026-08-16）**：历史 `RESEARCH_ONLY` 状态与 run 字节保持不变，但目标、NAV、
> 组合收益、换手和 0.5x/1x/2x 成本证据当前无效，不得进入 forward、S2/admission 或 PAPER。
> 不修改本页历史数值，也不为求翻案批量重跑；当前边界见
> [M2 执行路线图](../roadmaps/M2_策略与因子库并行建设路线图.md)。

## 1. 结论先行

预注册的 `max_daily_return_20` 通过了本轮全部历史初筛门禁：三个 validation folds 的原始方向均为冻结的
`-1`，三个 test folds 的方向化 RankIC 均为正，coverage、严格冗余和 20-session 调仓日对账全部通过，
2 倍成本后的跨 fold 链式收益为正。因此不可变 run 诚实落为 `RESEARCH_ONLY`，没有事后改方向、窗口、阈值
或 controls，也没有第二次真实 run。

这不是 `PAPER_CANDIDATE`，更没有启动 PAPER。当前结果仍来自 2019 年冻结流动性股票池和 research
diagnostics，缺历史动态 ST/行业/成分与正式市场事件回放；而且 1x/2x 组合在三个 folds 中各有两个 fold
为负，正的链式总收益主要由 2024 test fold 贡献。进入 forward 前还必须用 `daily_basic` 对规模与换手做
二阶段增量控制，并等待 post-freeze forward、统一回放与人工 admission。

机器产物当前暂存于短生命周期 worktree：

`artifacts/research/runs/10dea14f1fcbbbeb78871cddb7b00cd06d77cf005c3a776c4713f5a4f4129bb3`

目录含 14 个文件、463,198 bytes；`run.json` SHA256 为
`8180D41472DD205EEC47C37E95C2CC4E18DDE0F344A701DFE85EAE684DB1EF8C`，绑定 clean snapshot、配置、
代码和 13 个输出摘要。JSON 中没有 worktree 绝对路径。canonical retained 仍由统筹按 no-clobber、逐文件
size/SHA256 验真流程处置，本任务不移动或重签产物。

## 2. 数据、公式与时间合同

- clean snapshot：`b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2`；
- 输入股票日线 17,766,134 行；冻结候选池为 2019 年流动性 top 800；研究面板 1,230,269 行；
- 因子：`close × adj_factor` 的 20 个严格连续 session 简单收益的最大有符号值，需要连续 21 个价格；
- 固定经济方向：`-1`，即低 MAX 优先；validation 只检验方向，不翻转实际组合；
- 信号只使用 `as_of` 收盘可知数据，标签和诊断组合最早在下一 exchange session 开盘；
- walk-forward 使用三个时间顺序 folds；每 20 个预注册 session 调仓，top 50 等权 `target_weight`；
- 成本压力固定为 0.5/1/2 倍；trial budget 精确为 1；
- 本因子不是 Qlib Alpha158 的 `Max(high,20)/close`，生产列名保持 `max_daily_return_20`。

## 3. 门禁证据

| 门禁 | 实际证据 | 结论 |
|---|---:|---|
| validation 原始方向全部为 `-1` | 3/3 folds | 通过 |
| 平均方向化 test RankIC `>= 0.01` | 0.088201 | 通过 |
| 正 test folds 至少 2/3 | 3/3 | 通过 |
| 全部信号日 coverage 中位数 `>= 80%` | 99.3573% | 通过 |
| 每个预注册调仓日至少 100 个有效证券 | 最小 733 | 通过 |
| 实际调仓日逐 fold 精确一致 | 12/12、12/12、7/7 | 通过 |
| 最大 median abs RankCorr `< 0.80` | 0.623254，对 `alpha158_std20` | 通过 |
| 1 倍成本后跨 fold 链式收益 | 12.8549% | 通过 |
| 2 倍成本后跨 fold 链式收益 `> 0` | 6.3409% | 通过 |

三个 test folds 的方向化 RankIC 分别为 `0.074663 / 0.062873 / 0.127066`。2 倍成本下各 fold 组合收益
分别为 `-16.2771% / +36.0340% / -6.6297%`；1 倍成本下分别为
`-14.4749% / +39.3757% / -5.3240%`。这说明横截面 IC 较一致，但组合经济收益仍有明显时期集中，不能把
正的链式总收益描述成三段都稳健。

除 `alpha158_std20` 外，较高的冗余项包括 `alpha158_cord20`（0.467960）、`alpha158_sumd20`
（0.460869）和 `alpha158_roc20`（0.431512）；均未触发严格 0.80 线。若二阶段规模/换手控制后增量消失，
仍应降级而不是以本轮通过替代控制检验。

## 4. 性能与开发反馈

唯一真实 run 使用 Windows Miniforge、CPU8—11 affinity、BelowNormal，Polars/数值线程不超过 2，且未启动
第二个本任务研究 Python：

- 单调 wall time：79.365 秒；
- 完整进程 CPU time：36.797 秒；
- `PeakWorkingSet64`：2,724,503,552 bytes，约 2.54 GiB；
- 数据规模：17,766,134 输入行、1,230,269 面板行、1,603 个有效研究日、31 个预注册调仓日；
- 进程 I/O bytes 及 snapshot verify / query / factor / walk-forward / publish 分段耗时仍未捕获。

正常开发检查一次通过：focused `11 passed`，Ruff、mypy、py_compile 与 TOML 冻结校验均绿色。当前时间与
Alpha158 第四批约 93 秒 / 2.40 GiB 的基线同量级；由于仍无阶段 profile，不能据此归因 I/O 或计算热点，
也不能直接引入 GPU/并行重写。本次 immutable run 不为补指标重跑。

## 5. 后续处置

1. 按 no-clobber 和逐文件 SHA256 流程把本 run 保留到项目级 canonical research runs；
2. 不自动提交 S2 admission，不建立 PAPER 账户，不生成订单；
3. 财务 snapshot READY 后优先执行已冻结的 PIT 质量因子，不继续无界枚举 bar-only 公式；
4. MAX 的下一步仅允许新预注册的 `daily_basic` 规模/换手增量控制与 post-freeze forward，不在当前历史窗口
   内改变 20-session 窗口、`-1` 方向或 0.80 门禁；
5. 只有二阶段控制、forward、统一市场事件回放和人工批准都成立时，才可另行评估
   `PAPER_CANDIDATE`。
