# M2 `daily_basic` 价值代理因子假设卡

日期：2026-08-15
状态：公式、运行器与失效规则冻结；等待全量 clean snapshot 后首次评估
晋级上限：`RESEARCH_ONLY`；本假设卡不生成 `PAPER_CANDIDATE`、不启动 PAPER

## 1. 研究动机与边界

调研材料把 EP、BP、股息率等列为经典价值机制，并强调价值陷阱、财务可比性、行业差异和 Point-in-Time
约束。QIML 摘要中的账面市值比、盈利市值比等需要财务报表原值和公告时点；在财务四表尚未完成前，
不能冒充其精确复现。

本批只研究 Tushare `daily_basic` 每日历史截面自带的估值比率，作为低数据门槛的供应商口径代理。
它们用于尽早证伪“简单日频价值截面是否有增量信息”，不能替代后续基于
`income/balancesheet/cashflow/fina_indicator` 重建的 PIT 财务因子。

参考输入：

- [`00_因子体系与评估框架.md`](references/quant_factor_research_v2/00_因子体系与评估框架.md)；
- [`04_QIML_2024/02_二月.md`](references/quant_factor_research_v2/04_QIML_2024/02_二月.md) 的账面市值比；
- [`04_QIML_2024/08_八月.md`](references/quant_factor_research_v2/04_QIML_2024/08_八月.md) 的盈利市值比。

## 2. 冻结因子

| 因子 | 精确公式 | 初始方向 | 缺失/异常规则 |
|---|---|---|---|
| `daily_ep_ttm_positive` | `1 / pe_ttm`，仅 `pe_ttm > 0` | 高值优先 | 亏损、零值、null 记 null，不把负盈利收益率混入便宜公司 |
| `daily_bp_positive` | `1 / pb`，仅 `pb > 0` | 高值优先 | 负净资产、零值、null 记 null |
| `daily_sp_ttm_positive` | `1 / ps_ttm`，仅 `ps_ttm > 0` | 高值优先 | 非正、null 记 null |
| `daily_dividend_yield_ttm` | `dv_ttm / 100` | 高值优先 | null 保持 null；0 是合法不分红观测 |

`log(total_market_value)` 只作为规模暴露诊断，不是本批候选因子。公式实现位于
`src/quant/factors/daily_value.py`，不得在配置或回测脚本中复制另一套数值规则。

## 3. 时间与数据合同

- 每行值只在该 `trade_date` 收盘后视为可知；信号 `as_of` 为当日收盘，最早下一开市日开盘成交；
- 数据必须来自指定不可覆盖 `tushare_daily_basic` clean snapshot，通过窄 repository 读取；
- bar、标签和成交价继续来自既有 verified bar snapshot；`daily_basic.close` 不作为行情权威；
- 不对 null 做 0 填充，不用未来截面回填历史，不从后续财务表反推旧日供应商比率；
- SH/SZ 以外证券及股本/市值关系异常行只保留在 quarantine，不进入因子截面。

## 4. 首次评估协议

1. 沿用现有冻结 walk-forward 折、下一开市日开盘标签和流动性股票池；
2. 每个因子分别报告 coverage、null 原因、横截面分位、RankIC、ICIR、分组单调性和年度稳定性；
3. 方向只在训练/验证期确认，测试集只打开一次；
4. 同时报告与规模、既有价量因子的 Spearman 相关和增量 IC；
5. 组合输出仍是 `target_weight`，并执行 0.5x/1x/2x 成本压力；
6. run 使用不可覆盖 `run.json`，记录 snapshot、公式版本、universe、fold、成本和代码身份。

## 5. 预先冻结的否证条件

出现任一项即保持 `REJECTED` 或数据阻断：

- 完整 raw 审计不是 `READY`，或 clean snapshot/窄读取验真失败；
- 有效 coverage 过低、分年度大幅漂移，或 null 主要由不可解释的数据缺口造成；
- 测试期方向反转、RankIC/分组单调性不稳定；
- 信息被规模或既有价量因子近乎完全解释，缺少增量价值；
- 1x 无可复现净收益，或 2x 成本下经济意义消失；
- 结果依赖事后更换正负盈利处理、调仓频率、股票池或阈值。

即使统计结果为正，本批最多进入 `RESEARCH_ONLY`。历史证券池 PIT、行业可比性、价值陷阱过滤、
统一市场事件重放和冻结后的前向证据未关闭前，不得晋级 PAPER。

## 6. 可重现运行入口

运行器位于 `src/quant/research/run_daily_value_factors.py`，冻结参数位于
`configs/research/m2_daily_value_factors.toml`。配置只绑定既有 bar snapshot；新发布的
`daily_basic` snapshot id 必须由 clean publisher 实际输出后作为命令参数传入，不在配置中预填
虚假占位值：

```bash
python -m quant.research.run_daily_value_factors \
  --daily-basic-snapshot-id <publisher 输出的 64 位 snapshot id> \
  --data-root data --artifact-root artifacts --threads 2
```

运行器同时验真 bar 与 `daily_basic` 两个不可覆盖 snapshot。价值信号来自后者；冻结流动性股票池、
历史行数、下一开市日开盘标签和成交诊断只来自前者。输出额外包含每日 coverage 与对规模、六个既有
价量因子的冗余诊断；最大中位绝对 Rank 相关达到 0.80 时，即使其他门槛通过也按预注册规则拒绝。
