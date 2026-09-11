# 2026-09-11 日频行情完整性核对

**沪深股票与现有11只ETF池已到最新已收盘日2026-09-11；当日日线待补缺口为0。本轮新增11行真实ETF复权因子到独立clean版本。**

|表|09-11有效行/标的|本轮新增clean行|结果|
|---|---:|---:|---|
|沪深股票bar_1d|5207|0|已存在；交易股票均有basic与复权|
|沪深股票adjust_factor|5219|0|比成交股多12只，全部有当日S停牌记录|
|沪深股票daily_basic|5207|0|与当日成交股行集相同|
|ETF bar_1d|11/11|0|池内缺口0|
|ETF research_price_1d|11/11|0|TOTAL_RETURN_DIVIDEND口径，池内缺口0|
|ETF fund_adj|11/11|11|供应商真实复权因子，独立新切片|
|ETF daily_basic|不适用|0|daily_basic为股票每日指标接口|

当日各表重复键均为0。股票三张clean表由09-11既有raw重新规范化后逐值相同。差集12只：000016、002731、002870、301139、301390、600825、600929、603159、605577、688291、688432、688496；当日suspend_d逐只为S，不能补造零成交日线。沪深日历最近开市日均为09-11。

实际入口结果：`refresh_stocks`与`refresh_etf_prices`均返回`no-op`、latest_date=2026-09-11，原日线新增0。补充调用限定09-11：1次suspend_d（13行，含1条复牌）及11个ETF各1行fund_adj；应用中断后复用了已保存的8次响应，仅续取剩余4只ETF。原先510300基准raw已有当日因子，这次同日单标的查询再确认，其余10只补入本次池级切片。

**复用路径：**
- 股票三表：`data/clean/tushare_incremental/date=2026-09-11/{bar_1d,adjust_factor,daily_basic}.parquet`；历史加增量仍使用既有`read_stock_data`。
- ETF日线/总回报：`data/clean/bar_1d/date=2026-09-11/data.parquet`、`data/clean/research_price_1d/date=2026-09-11/data.parquet`。
- 新ETF真实复权：`data/clean/etf_daily_slices/snapshots/daily_freshness_20260912_01/adjust_factor.parquet`；11行便查版见本目录`etf_adjust_factor_20260911.csv`。
- 逐接口raw路径、停牌明细、表计数和缺口：`coverage_summary.json`；原完整行集结果：`result.json`。

一次命令：`$env:PYTHONPATH='F:/AI_Coding/QuantitativeTrading/src'; D:/Miniforge3/python.exe -m quant.data.daily_freshness_20260912`。专属配置：`configs/data/daily_freshness_20260912.toml`，关闭财务/因子/行业/质量流水线并直接调用两个日线入口；再次运行读取已完成结果。定向单测、Ruff、mypy通过。

**关键口径：**现有ETF bar的adj_factor全为1是映射默认值，本轮未将其当作真实因子；新fund_adj切片与原现金分红总回报序列分开保存，不替换历史研究输入或主刷新配置。股票basic原规范化仍保留4行自由流通股不合法值置空的既有处理，不能把行集齐全解释为所有估值字段非空。

接口定义参考：[股票每日指标](https://tushare.pro/document/2?doc_id=32)。
