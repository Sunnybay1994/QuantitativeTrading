# M3 G1 Benchmark Close-Only 设计阻断与决策记录

## 现象

- 唯一 `H00300.CSI index_daily` receipt 共 `2614` 行，日期 `2015-10-09..2026-07-10`。
- `2273` 行 `open/high/low=null` 且 `close>0`；只有 `341` 行完整 OHLC，范围仅 `2021-09-15..2023-02-17`。
- 配置 signal domain 为 `2016-01-04..2026-06-26`，minimum train sessions 为 `756`；341 行中间窗口不能满足现有实验。
- 真实 traceback：`_build_candidate_body:1474 -> map_g1_benchmark_response:179 -> _parse_ohlc:376 -> _parse_positive`，稳定底层码 `G1_MAPPER_VALUE_INVALID`。

## 冲突的权威契约

- `docs/M3实施与Agent交接.md` 冻结：证券和 `H00300.CSI` 都使用同一 `open(t+1) -> close(t+h)` 区间，且 benchmark 必须通过含 OHLC 的 `BenchmarkBar1dSchema`。
- 中证指数官方方法说明全收益指数考虑税前现金红利再投资，并给出交易日收盘点位的计算方法；其开盘参考价是成分股层面的公司行动调整参考价。该方法不能把供应商 close 直接复制成指数 open/high/low，也不能仅凭一个价格指数比例无证据地还原权威全收益指数开盘。
- Tushare raw 已证明当前 `H00300.CSI index_daily` 不能覆盖冻结 OHLC 契约。

## 禁止的伪修复

- 不得以 `close` 填充 open/high/low。
- 不得静默改用 `000300.SH` 价格指数后仍称全收益 excess return。
- 不得只裁剪到 341 行 OHLC 中间窗口并声称满足 756-session 训练门槛。
- 不得用未经方法学证明的比例公式合成开盘，或使用未来 close 信息制造 entry open。

## 需要用户确认的路线

1. **保持现有研究口径**：引入能提供 2016–2026 权威全收益指数 OHLC/可验证开盘序列的数据源；最忠实，但需要新数据源、凭据/许可与来源闭包设计。
2. **改为可交易 ETF 基准**：例如 510300.SH 的复权 open→close；可保持可成交区间，但 benchmark 身份变为
   含跟踪误差和费率的 ETF，不再是 `H00300.CSI`。当前 G1 connector 尚无 `fund_daily/fund_adj` 角色，
   账号权限和全历史覆盖也未探测，因此必须先建有界权限探针和 raw/receipt 合同，不能表述为现成两次请求。
3. **改为价格指数**：使用 `000300.SH` OHLC；实现最简单，但不含分红再投资，长期 excess return 系统偏差最大，不建议。

这是会改变标签、模型目标和最终超额收益解释的架构决策；在确认前，主 Agent 不修改 benchmark Schema、label version 或配置。

## 2026-07-18 决策影响补充

| 路线 | 新数据与实现 | identity / 科学解释影响 | 裁定 |
| --- | --- | --- | --- |
| A 保持 `H00300.CSI` | 新增具许可的权威 full-OHLC connector、raw journal、receipt 与来源闭包 | 经济语义可保持；仍须把 source/method/license lineage 纳入 G1 与下游 hash | 科学最忠实；仅在已有可许可权威源时选择 |
| B `510300.SH` 复权总回报 | 先探测基金行情/因子权限，再新增 endpoint role、mapper、receipt；本地混合来源 851 行不可直接复用 | `label_version` 必须升级为 ETF proxy；G1、snapshot、G3–G9 identity 全变，包含跟踪误差、费率和溢折价 | **务实推荐**，但须先证明基金历史与因子闭包可用 |
| C `000300.SH` 价格指数 | 现有 `index_daily` 结构可复用，仍需一条 exact 新 request/receipt | `label_version` 必须升级为 price-index excess；长期超额会包含遗漏的指数股息贡献 | 技术最快、科学偏差最大，不推荐 |

`3185` 个证券 HISTORY receipts 在三条路线下均保留且不得覆盖；旧 H00300 receipt 也作为失败事实保留。
B/C 改 code 时不得只换 selector：benchmark mode/source/method、label version、G1 release、snapshot、scientific/full
config 以及全部下游 artifact identity 必须一起重基线。

## 2026-07-22 用户决策与权限复核

- 用户确认选择路线 B，benchmark 固定为 `510300.SH` 可交易 ETF 代理；A 股全流程闭环优先于港股历史补洞。
- Tushare 当前官方权限表显示：`fund_daily` 与 `fund_div` 的最低门槛均为 2000 积分，`fund_adj` 为
  5000 积分起。当前账号是 2000 积分档，因此首版不得把 `fund_adj` 当作可用前置，也不得调用股票
  `adj_factor` 冒充 ETF 复权因子。
- 在真实探针证明字段和覆盖前，冻结的可行候选是：`fund_daily` 未复权 OHLC + `fund_div` 已实施现金分红
  事实，按明确的除权/支付时点规则构造 `510300.SH` 总回报 OHLC。该序列仍是 ETF 代理，包含跟踪误差、
  管理费和溢折价，不恢复 `H00300.CSI` 的指数身份。
- 先执行 [`M3_G1_BENCH-B0_510300ETF基准源探针与合同冻结任务单.md`](M3_G1_BENCH-B0_510300ETF基准源探针与合同冻结任务单.md)。
  B0 只允许最多两次 raw-first 请求，不修改生产合同；字段、权限或历史覆盖任一失败即停止 B 路线实现并
  回到设计裁定。
