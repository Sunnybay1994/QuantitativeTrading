# M3 G1 BENCH-B0：510300 ETF 基准源探针与合同冻结任务单

## 1. 目标与边界

用户已选择 `510300.SH` 作为可交易 ETF 总回报代理。本任务只验证 2000 积分账号可用的数据源、字段和
最小覆盖，不修改生产代码、配置、Schema、既有 HISTORY request/receipt 或 G1 release。

权威前置：

- benchmark code：`510300.SH`；
- 原始行情候选：Tushare `fund_daily`；
- 公司行动候选：Tushare `fund_div`；
- `fund_adj` 官方最低门槛为 5000 积分，不属于当前实现前置；
- 既有 `H00300.CSI index_daily` raw/receipt 永久保留为失败事实，不覆盖、不删除。

## 2. API 预算与 raw-first 规则

最多执行两次真实请求，每个 endpoint 恰好一次：

1. `fund_daily(ts_code=510300.SH, start_date=20260701, end_date=20260710)`；
2. `fund_div(ts_code=510300.SH)`。

响应必须先写入 `data/raw/tushare/` 下独立 probe table，保存 endpoint、完整非敏感参数、抓取时间、行列、
Parquet SHA-256 和 metadata SHA-256。token 不得进入终端、日志、metadata、任务书或 Git。

## 3. B0 通过条件

- 两个接口均在当前账号下成功返回 DataFrame；
- `fund_daily` 至少含 `ts_code,trade_date,open,high,low,close`，请求窗口内存在 `510300.SH` 正价格 OHLC，
  无目标外代码和重复交易日；
- `fund_div` 的真实列足以唯一识别公告、除权/权益和现金分红语义；空历史也必须作为完整 raw 事实保留，
  但空历史本身不证明长期总回报可构造；
- raw pair 可由 `RawStore.verify_request_bundle` 重读，metadata 不含 token。

任一条件失败时，B0 结论为阻塞；不得继续实现 B1、不得降级成未复权价格基准、不得静默改用
`000300.SH`。

## 4. B1 冻结设计输入（仅在 B0 通过后生效）

外部实现 Agent 必须在新的任务书白名单内完成，另一全新外部会话只读初验：

- 为基金行情与基金分红建立显式 endpoint role、fields、row limit、request/receipt 和 mapper；
- benchmark mode/source/method 进入配置、build spec、manifest、snapshot 和全部下游 identity；
- `label_version` 升级，名称必须明确 `510300` ETF proxy 与 total-return 方法版本；
- `BenchmarkBar1dSchema` 可继续容纳可交易代码，但 mapper/候选审计不得再硬编码 `H00300.CSI`；
- 总回报算法必须使用当时可知且已实施的现金分红事实，明确 entry open 到 horizon close 区间内的权益归属；
- 证券 HISTORY 的 3185 份既有 receipts 保持不变，只新增 benchmark 所需的不可变请求身份。

## 5. 对抗性反例与后续测试要求

- `fund_daily` 返回其他代码、重复日期、缺失/非正 OHLC 或触及 row limit：fail closed；
- `fund_div` 只有公告日而无可用实施/除权日期，或同一事件冲突：fail closed；
- 将股票 `adj_factor`、ETF 未复权 close 或未来公告事实注入总回报：必须拒绝；
- 只替换 benchmark selector 但保留旧 label/config/snapshot identity：必须被身份测试捕获；
- 分红发生在 entry 之前、entry 与 exit 之间、exit 之后三种边界必须分别验证，禁止未来信息穿越。

## 6. 2026-07-22 B0 结果与 R1 追加裁定

B0 两次请求均成功并通过 `RawStore` 重读：

| endpoint | request_id | rows | raw SHA-256 |
| --- | --- | ---: | --- |
| `fund_daily` | `ab8add91a5e32495bfc6f9ad06bf8f5e60957b98616e3963627b3bad9e5bd6a6` | 8 | `9690a9bb5dbf4efc1132a04a648c91b8c7540b40f13702b2ee39a6563f3937c5` |
| `fund_div` | `dfda08c2aa2324607ae650054719f131a3ff0c3bcc5f16fdcec9f39e6127ae4e` | 22 | `39b3012fefd6d9a067aceb2da7af007256cd36bd5507085684bf7fb324267e7b` |

`fund_div` 覆盖 2012-12-18..2026-01-19，22 行均为“实施”。投影到
`(ts_code,ann_date,imp_anndate,record_date,ex_date,pay_date,div_cash)` 后存在重复事件：部分全行重复，
部分只在 `net_ex_date/base_unit` 不同。B1 mapper 必须先按经济事件键分组，要求核心字段一致后只投影一条；
同组 `ex_date/div_cash` 冲突时 fail closed，禁止把重复行累计为双倍分红。

Tushare 当前官方权限总表与 endpoint 详情页对 `fund_daily/fund_adj` 门槛表述不一致，且当前 2000 积分
账号已经成功调用详情页声称需要更高门槛的 `fund_daily`。为消除真实能力不确定性，批准 R1 追加且仅追加
一次请求：

`fund_adj(ts_code=510300.SH, start_date=20260701, end_date=20260710)`。

该请求仍须 raw-first 写入独立 probe table。若成功且含唯一的正 `adj_factor`，B1 以 `fund_daily + fund_adj`
构造供应商总回报 OHLC，并用 `fund_div` 做实施事件对账；若失败，则回到 B0 的现金分红构造路线。R1 不得
重试，也不得扩大日期窗口。

### R1 结果

R1 一次请求成功，返回 8 行、列精确为 `ts_code,trade_date,adj_factor`，窗口内因子均为 `1.2671`；raw pair
通过重读且 metadata 不含 token：

- request_id：`e3fc87ac784b9285d7b5497bfc2964c4eda4828ad0652eafaba748480afdeaab`
- raw SHA-256：`5908185e65487db274c9bc10f230db54f849695485afbdc534ec077a88932b97`
- metadata SHA-256：`570536a200c6e5d57f108c37bcb453c2f218dd4f4a7af54a0dd2b96b1b41042f`

B0/R1 通过，B1 解冻。正式 HISTORY 仍须按 `fund_adj` 单次 2000 行的 endpoint 上限确定性分段，并对
`fund_daily`、全部 `fund_adj` 分段和 `fund_div` 分别形成不可变 request/receipt 闭包；探针 raw 不直接
充当正式 receipt。

## 7. B0-R2：除息日前后对账公式探针

`fund_div` 已证明 `510300.SH` 在 2026-01-19 除息、每份派息 `0.123`，但小窗 B0/R1 位于 7 月，不能证明
供应商 `fund_adj` 的跳变日期与计算关系。为冻结 B1B mapper，R2 仅允许两次请求：

1. `fund_daily(ts_code=510300.SH,start_date=20260115,end_date=20260121)`；
2. `fund_adj(ts_code=510300.SH,start_date=20260115,end_date=20260121)`。

两者必须各调用一次、raw-first 写入独立 `*_exdiv_probe` table，不重试、不扩大窗口。对账应检查：除息日前
一开市日、除息日均有 raw close/factor；因子只在可解释日期跳变；实际因子比与
`previous_close / (previous_close - div_cash)` 的关系由真实结果裁定，不预设容差或强行相等。

### R2 结果与公式冻结

R2 两次请求均一次成功并通过 `RawStore` 重读，未重试、未扩大窗口：

| endpoint | request_id | rows | raw SHA-256 | metadata SHA-256 |
| --- | --- | ---: | --- | --- |
| `fund_daily` | `84432ae17f4ee27fbd923e358399129e0ebca47c1267cd4bbd5c23b5205e3879` | 5 | `92aaf235d80ffc50cc2787aed0b58783561a6c652d37f772561c20e1105cae20` | `3ffebadd49bf4502b8099580f5d84981a84d51a77da81288efe70c266e0a53fc` |
| `fund_adj` | `65a5c9aba005323ed59ec85e02ac5f2e62200013fdcf40e7a86994af3eed7f67` | 5 | `311c0f39e259c200cf114bb83a166b2e98d2561725539a5529ae9083827ff906` | `405200a3b3ca2384810292eab8e4ea9e779bc939265964ed7b40f2806c6ac3f3` |

关键观测：

| trade_date | pre_close | close | adj_factor |
| --- | ---: | ---: | ---: |
| 2026-01-15 | 4.866 | 4.875 | 1.2350 |
| 2026-01-16 | 4.875 | 4.859 | 1.2350 |
| 2026-01-19 | 4.736 | 4.738 | 1.2671 |
| 2026-01-20 | 4.738 | 4.724 | 1.2671 |
| 2026-01-21 | 4.724 | 4.730 | 1.2671 |

`fund_div` 的已实施事件为 `ex_date=2026-01-19, div_cash=0.123`。真实数据满足：

- `previous_close - div_cash = 4.859 - 0.123 = 4.736`，与除息日 `pre_close` 精确一致；
- 实际因子比 `1.2671 / 1.2350 = 1.0259919028340079`；
- 价格/现金比 `4.859 / 4.736 = 1.0259712837837838`；
- 两者绝对差为 `0.000020619050224102153`，落在项目既有相对容差 `rtol=0.001` 内。

据此冻结 B1B 对账公式：对每个窗口内已实施现金分红事件，除息日必须存在因子跳变；先验证
`ex_day.pre_close ~= previous_close - div_cash`，再验证
`ex_day.factor / previous_day.factor ~= previous_close / ex_day.pre_close`。两项均使用既有
`rtol=0.001`，且必须同时成立；缺失日期、非正分母、无事件的因子跳变、事件存在但因子不跳变或核心字段冲突
均 fail closed。不得使用 `ex_day.pre_close / (ex_day.pre_close - div_cash)`，也不得重复累计
`fund_div` 的供应商重复行。
