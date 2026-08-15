# M2 Tushare PIT 基本面数据可行性审计

日期：2026-08-15
状态：`daily_basic` 全历史已审计、发布并完成真实研究；VIP 无权限，财务四表转入 regular 五年分片采集

## 1. 审计结论

当前 verified clean snapshot 足够支持日线价量研究，但尚不足以支持 PIT 基本面策略。已自然完成的
24,343 个 raw 请求只包含：

| dataset | COMPLETE requests | raw rows |
|---|---:|---:|
| `daily` | 8,704 | 18,107,780 |
| `adj_factor` | 8,704 | 18,935,088 |
| `fund_daily` | 6,935 | 3,145,969 |
| `fund_adj` | 1,598 | 1,406,345 |

Ledger 中原本没有 `daily_basic/income/balancesheet/cashflow/fina_indicator` 请求；因此不能用
“核心历史采集完成”推断基本面数据也已就绪。

## 2. 权限与计划

2026-08-15 使用 catalog `2026-08-15-v2` 重新探测后的权限结论为：

- `daily_basic`：ACCESSIBLE；
- `income/balancesheet/cashflow/fina_indicator`：ACCESSIBLE；
- `income_vip/balancesheet_vip/cashflow_vip/fina_indicator_vip`：全部 `PERMISSION_DENIED`；
- `disclosure_date`：EMPTY_BUT_VALID，仍需代表参数复核，不作为当前 PIT 的必要依赖。

VIP 窄探针报告为
`data/run_state/tushare_bulk/permission_reports/20260815T094032.311210Z-6f85c67350e6.json`；随后在同一
catalog 身份下补测 regular 四表，合并权限报告为
`data/run_state/tushare_bulk/permission_reports/20260815T094049.683862Z-9d64b19721e3.json`。报告只保存脱敏
状态与行数，不包含 token 或配置内容。VIP 权限拒绝是供应商权限边界，不能通过换参数或复制接口规避。

现有 dry-run 估算：`daily_basic` 6,450 个按交易日请求。财务四表不能再按“每个证券一个无日期请求”
估算：官方 `fina_indicator` 明确单次最多返回 100 行，长历史证券会被静默截断。regular fallback
现改为每证券五年窗口；按当前 5,537 个 SH/SZ 股票和 1990 年起始日估算，每端点约 44,296 个请求，
四表约 177,184 个。2026-08-15 的离线计划实际确认当前库存为 5,537 只沪深股票、每表 44,296 个请求、
四表合计 177,184 个；计划保存在
`data/run_state/tushare_bulk/plan_reports/20260815T094124.671741Z-a227e9cc51f5.json`。库存包含沪深
334 只 `DELISTED` 股票，不是只取当前上市公司。VIP 端点无权限，因此正式选择 regular fallback。为避免
多 writer、接口争用和桌面资源干扰，必须顺序执行：

1. 先完成 `daily_basic`；
2. 质量审计后再启动四个财务端点；
3. raw 完成不等于 clean/PIT 可用，必须另做 Schema、业务键、修订链与公告时点门禁。

在写入长任务 ledger 前，另用 `000001.SZ` 的 2019-01-01 至 2023-12-31 五年窗口做了不落盘的真实请求
检查：`income/balancesheet/cashflow/fina_indicator` 分别返回 30/30/26/37 行，距 6,000/6,000/6,000/100
行上限均有明确余量。三张报表实际包含 `ann_date/f_ann_date/end_date/update_flag/report_type/comp_type`；
财务指标包含 `ann_date/end_date`。这只证明分片与字段入口可用，不替代全量完成后的逐请求行上限、业务键、
修订链和公告时点审计。

四表 177,184 个请求已加入可恢复 ledger，后台单 writer 于 2026-08-15 启动，固定 60 次/分钟；stdout/stderr
分别写入 `data/run_state/tushare_bulk/logs/finance-regular-r1.stdout.log` 和
`finance-regular-r1.stderr.log`，半小时 heartbeat 只监测，不自动重启或改写状态。首批 partial raw 还揭示：
供应商 SDK 会把“整次请求均为空”的数值列推断成字符串，而有值请求中同列是浮点，直接纵向读取 raw
Parquet 会发生 Schema drift。因此 clean publisher 必须先按权威字段表显式转换并对非空不可解析值
fail-closed；不能依赖 Parquet 自动推断或把空字符串静默转成 0。该结论来自 partial 预诊断，不是全量
snapshot 通过证据。

2026-08-15 在资产负债表推进到 1,151 COMPLETE、1 RUNNING、43,144 PENDING 时，使用只读入口
`python -m quant.data.audit_tushare_financials` 做了第二次 partial 审计。当前 11,978 行在逐请求物理行数、
请求证券、五年窗口、关键空值、日期、必需数值解析和非有限值上均为 0 异常；3,370 组同一业务键、
同一可知日的重复行中，必需经济字段冲突为 0，符合 `update_flag=0/1` 的相同经济值成对出现，而不是可
任意择行的经济冲突。当前只有 43 个业务键形成跨公告日修订链，仍是早期样本，不能外推为全量分布。
DuckDB `union_by_name` 同时确认必需资产负债数值列的联合物理类型会成为 `VARCHAR`，再次证明 clean
必须显式解析。审计总状态仍为 `COLLECTING`、阻断项 0、`publication_allowed=false`；这不是 clean
发布或因子可用证明。

为把已经证实的 Schema drift 处理规则下沉为可测试代码，新增了纯内存
`quant.data.financial_clean.normalize_tushare_financial_frame`：它只投影首批研究所需字段，把可解析的
字符串/数值统一为 Float64，保留合法 null，并把非空不可解析值、NaN/Inf、非法日期/证券和结构字段显式
隔离；不会填 0、不会解决修订冲突、不会读取共享目录或发布 partial snapshot。对应 factor 投影函数只把
PIT selector 已选出的报表视图转换为 `symbol + Date end_date` 合同。9 项定向测试覆盖物理类型漂移、
空值、非法经济值、结构异常、update_flag 成对去重、输入逆序、factor 投影与稳定错误。全量 raw 达到
`READY + --verify-bytes` 前，publisher 和 repository 仍保持未实现。

随后又从当前 immutable raw 中只读选择了两种实际资产负债表物理 Schema：
`(total_assets=Float64, parent_equity=Float64)` 与
`(total_assets=Float64, parent_equity=String)`。两类请求分别有 8/4 行，均经同一标准化函数得到 Float64
经济字段、0 quarantine；这证明转换路径不仅在合成 fixture 上成立，同时没有把这个有限样本冒充全量
clean 通过证据。

采集等待期间已把终态后的发布与读取路径实现为
`quant.data.publish_tushare_financials` 和 `quant.data.financial_repository`。publisher 每次先执行
`READY + verify_bytes` 全量审计，以完整 audit/raw request-set 与 projection version 生成 snapshot id，
按 `dataset/year` 写 typed ZSTD Parquet，并在提交前后重新验真；同一身份只能严格复用，已发布文件漂移
必须拒绝，不能覆盖。repository 只接受 snapshot id、单一 dataset、有限报告期和排序去重的证券集合，
在读取前后验真同一 snapshot，返回完整修订历史供同一个 PIT selector 重复使用，避免 walk-forward 每个
`as_of` 都重新扫描 raw。小型四表完整 fixture 已覆盖 typed 发布、严格复用、partial 禁止发布、内容漂移
拒绝、bounded read、空窗口和严格晚于公告日的修订选择；加上研究侧月末 PIT 信号构造后，当前财务链
合计 38 项定向测试通过。

这些接口尚未对共享财务目录执行真实发布。当前 ledger 仍是 `COLLECTING`，因此真实调用必须稳定拒绝；
只有四表自然完成、全字节审计为 `READY` 后，才能生成第一个真实财务 clean snapshot。

### 2.1 官方契约与采集分片修正

官方文档确认：

- [利润表](https://tushare.pro/document/2?doc_id=33)、[资产负债表](https://tushare.pro/document/2?doc_id=36)
  和 [现金流量表](https://tushare.pro/document/2?doc_id=44) 均支持 `ann_date/f_ann_date/start_date/end_date/period/report_type/comp_type`，
  且输出保留 `report_type/comp_type/update_flag`；
- [财务指标](https://tushare.pro/document/2?doc_id=79) 按单只股票获取历史，单次最多 100 行，输出
  `ann_date/end_date/update_flag`；
- [披露计划](https://tushare.pro/document/2?doc_id=162) 的 `pre_date/actual_date/modify_date` 是披露计划与
  修订证据，不能代替报表自身实际公告日。

代码审计发现 dry-run 规划器一直按 `chunk_days` 计算 `per_symbol` 时间片，但 `prepare_requests` 实际只
生成一个无日期请求。该缺口已修复为逐证券、逐不重叠 `start_date/end_date` 窗口，相关 9 项测试通过。
正式 catalog v2 将四个 regular 财务端点收窄为五年窗口，并把 `fina_indicator.max_rows` 冻结为官方
100 行：任一窗口达到 100 行即进入 `SPLIT_REQUIRED`，不得写成“完整”。同时加入四个 VIP 端点的
只探测 `manual` 条目；在完成真实权限和单季行数探针前，它们不能进入 ledger。

由于 catalog 身份已更新为 v2，`daily_basic` 批次按原 ledger 身份完成；该批次的审计和
发布绑定既有 request/metadata 字节，没有回写身份。后续 finance prepare 必须使用 v2 新权限报告，禁止
复用旧 catalog 的权限报告。

`daily_basic` writer 已退出且 ledger 无活动 lease；财务采集前已执行下列四请求窄探针：

```bash
python -m quant.data.tushare_bulk probe --data-root data \
  --config configs/tushare.local.toml --requests-per-minute 60 \
  --dataset income_vip --dataset balancesheet_vip \
  --dataset cashflow_vip --dataset fina_indicator_vip
```

探针结果为四个 VIP 全部 `PERMISSION_DENIED`。四个 VIP 条目继续保持 `manual`，不能由 generic prepare
自动写入 ledger；后续只允许把四个已验证 `ACCESSIBLE` 的 regular 数据集按五年窗口加入 ledger。

## 3. `daily_basic` 首批字段证据

2026-08-15 已把 6,450 个请求加入同一可恢复 ledger 并启动后台采集。首个非空 immutable raw
样本为单交易日 2,002 行，字段包括：

`ts_code/trade_date/close/turnover_rate/turnover_rate_f/volume_ratio/pe/pe_ttm/pb/ps/ps_ttm/
dv_ratio/dv_ttm/total_share/float_share/free_share/total_mv/circ_mv`。

样本显示估值和分红字段存在合法 null，不能以 0 填充；总股本、市值字段需要在 clean Schema 中
明确供应商单位。`daily_basic.close` 只用于源内一致性复核，不能替代已验真的 bar close。

启动后首个观测点：50 COMPLETE、6,399 PENDING、1 RUNNING；后台进程响应正常、stderr 为空。
30 分钟 heartbeat 已更新为跟踪本批次，禁止自动重启或自动启动下一批。

为避免把正在采集的数据直接升级为策略输入，已新增独立的 `DailyBasic1dSchema` 与只读审计入口
`python -m quant.data.audit_tushare_daily_basic`。它不修改既有四表 bar snapshot v1，也不发布 partial
clean；只有全部请求完成且关键质量项为零时才返回 `READY`。clean 单位冻结为股和人民币元，raw
`total_share/float_share/free_share/total_mv/circ_mv` 进入 clean 前统一乘以 10,000；raw
`daily_basic.close` 仅做源内一致性复核，bar close 仍由行情 clean 产物提供。ledger 行数与 Parquet
物理行数按 `request_id` 逐请求对账，不能用一个请求的多行抵消另一个请求的少行。

发布前复核发现 audit v1 的 source identity 只包含请求数、总行数和质量汇总，无法区分“统计相同但 raw
内容不同”的两批数据。该缺口已在首次真实发布前修正为 audit v2：排序后的 raw closure 逐请求绑定
`request_id/catalog_sha256/trade_date/rows/max_rows/data SHA-256/metadata SHA-256`，publisher 的
`snapshot_id` 自动包含该 closure。相关回归证明，只改变一个经济字段或只改变 metadata 抓取时间，即使
全部质量统计不变，也必须产生不同 snapshot identity；相同身份不能覆盖不同字节。

2026-08-15 的一次并发只读观测为 862 COMPLETE、5,587 PENDING、1 RUNNING，共 2,374,991 行，
业务键无重复、请求日期无错配、关键字段无 null/非有限/非正值，状态为 `COLLECTING`。当前可见的
37,856 条非 SH/SZ 行、179 条股本关系异常和 1 条市值关系异常进入显式 quarantine 统计；这些是
阶段性观测，不是全量终态。采集完成后必须重新执行带 `--verify-bytes` 的全量审计，才能决定 clean
发布范围和是否需要异常明细隔离。

2026-08-15 全量终态为 6,450 COMPLETE、17,200,294 raw 行。audit v2 带
`--verify-bytes` 逐请求对账后为 `READY`：唯一键数等于 raw 行数，行数、参数日期、关键空值、
非有限值、必需正值、负比例和静默行上限均无阻断。raw request-set SHA-256 为
`ba3d893d814dc0c86609d08abd62644bd61f7a7b14e6771d66381ac3cfe0b71d`。

clean 已按下列命令实际发布：

```bash
# 采集全部完成后先运行；非 READY 会以稳定错误拒绝发布。
python -m quant.data.audit_tushare_daily_basic --data-root data --verify-bytes
python -m quant.data.publish_tushare_daily_basic --data-root data --threads 2
```

发布物位于
`data/clean/tushare_daily_basic/snapshots/e97c0e9c82c445bbc9b389e8e8504f61b0b67d2f789208f75625526c38b4c03c/`，
按年保存 ZSTD Parquet，共 16,949,896 条 clean 和 250,398 条 quarantine，并包含
canonical audit、manifest 和 quarantine。相同 raw/audit/projection 只会严格复用同一 snapshot；文件、
目录或 manifest 漂移会被 verifier 拒绝。策略和因子不遍历该目录，而通过
`TushareDailyBasicQuery` + `read_tushare_daily_basic` 绑定 snapshot、日期窗口和可选证券集合做窄读取。

价值代理研究已绑定 daily-basic 与既有 bar 两个 snapshot 完成；不可覆盖 Run
`05606a6502cf23f2c3c6cfa69d81147eb2ee8260e99c6e637c7a6ed9741b4015` 保留 BP/股息率为因子级
`RESEARCH_ONLY`，拒绝 EP/SP。详细证据见
[`M2_daily_basic价值代理因子研究结果.md`](../research/M2_daily_basic价值代理因子研究结果.md)。

采集推进到 3,003 COMPLETE 时做过一次 2 线程、非字节验真的 partial 字段预诊断：当前 8,212,140 条
沪深记录中，`pe_ttm/pb/ps_ttm/dv_ttm` 覆盖率分别约为 82.9%/99.1%/99.9%/64.0%。非空
`pe_ttm` 和 `pb` 当前均为正，`ps_ttm` 有 46 条非正；非空 `dv_ttm` 均大于 0，说明供应商历史中的
“无分红”主要表现为 null，不能擅自补 0。该统计来自未完成批次，只用于提前验证缺失语义和公式防御，
不作为正式 coverage、因子表现或 snapshot 通过证据；终态必须重新计算。

## 4. PIT 通过条件

首批研究公式、公告日滞后、累计转单季、修订选择和非金融边界统一由
[`M2_PIT财务质量因子首批假设卡.md`](../research/M2_PIT财务质量因子首批假设卡.md) 冻结；本数据审计只负责
证明 raw/clean 是否足以执行该合同，不在这里复制第二套因子定义。

财务数据只有同时满足以下条件才可进入策略：

- `ts_code/end_date/ann_date/f_ann_date/report_type/comp_type/update_flag` 的实际字段与覆盖已核验；
- 同一报告期多版本按公告可知时间保留，不以最新修订覆盖历史；
- `as_of` 只选 `f_ann_date`（缺失时 `ann_date`）或更保守可知日不晚于知识截止日的版本；
- 累计报表与单季值转换规则版本化，不能把累计流量直接当季度流量；
- 业务键重复、空值、单位、极值和跨表恒等式通过质量门禁；
- clean 产物不可覆盖，并绑定 raw request 集合与内容摘要。

任一条件不满足时，价值—质量策略保持数据阻断，不得用当前最新财务截面回填历史。

PIT 修订选择的纯内存基础能力已落在 `src/quant/data/financial_pit.py`：公告可知日取两公告字段较晚值，
只有严格早于信号 `as_of` 的版本可见，每个业务键只取最新可知版本，同一最新可知日的经济字段冲突整组
quarantine，绝不退回旧版本或按行序/hash 决胜。6 项定向测试已覆盖同日不可见、缺一公告日、修订、
冲突、完全重复和输入逆序；这只是算法合同，只有全量 raw 审计和不可覆盖 clean snapshot 完成后才能
成为研究输入。
