# M1 HK-INSTRUMENT-R2A HKEX ETP 权威补全任务单

日期：2026-07-18  
执行者：主 Agent（24 小时简化流程；不调用外部 Agent）  
状态：已撤回（2026-07-18；发现许可冲突，公共网页 connector 已 fail closed）

> 纠正说明：HKEX 2025-08-19 更新的现行 Terms of Use §5 禁止未经书面许可的程序化/脚本化访问、
> 系统性抓取和建库。本任务最初把网页 JSONP 端点误当作可用于生产采集的公开 API，违反应先核对许可
> 的系统不变量。原完成结论撤回；详情见
> [`M1_HK-INSTRUMENT-R2A-CORR_HKEX网页采集合规撤回主Agent验证报告.md`](M1_HK-INSTRUMENT-R2A-CORR_HKEX网页采集合规撤回主Agent验证报告.md)。

## 1. 目标

以 HKEX 官方 Exchange Traded Products 页面及其公开数据端点为权威来源，为 2026-07-10 双 Route
eligible 集合中缺少 Instrument 引用的 31 个 ETF 补齐 `list_date`、`board_lot`、名称、币种和类型。
本任务不处理临时股票柜台 `02983.HK`，也不改变 Tushare 股票 mapper。

HKEX 真实探针已证明 31 个目标在 2026-07-10 均存在唯一最新记录，币种均为 HKD、产品子类均为
`ETFs`，且 `first_trade_date` 与正整数 `lot_size` 完整。

## 2. 冻结接口与选择语义

- 新增窄 `HkexEtpConnector.fetch_etp_instruments(target_symbols, as_of)`；不实现无关的 BaseConnector
  行情/日历接口。
- 每次先读取官方 ETP 页面，从未注释的 `LabCI.getToken` 返回语句动态提取 token；禁止硬编码、落盘、
  输出或在异常中回显 token。
- 数据请求固定使用官方 `getetpexportdata` JSONP 端点，`lang=en`、`all=1`、`sort=1`、`order=1`，
  日期起止均绑定 `as_of`。
- JSONP callback 必须完整匹配；JSON 拒绝重复键与 `NaN`/`Infinity`；响应必须
  `responsecode == "000"` 且含字典数组 `DBDataList`。
- connector 只返回显式目标代码的原始行，不发布全量 ETP。
- mapper 只考虑 `trade_date <= as_of` 的记录；每个目标选择最大 `trade_date`。最新日重复行若五个身份字段
  完全一致可折叠，任何冲突均 fail closed。
- `trade_date` 与 `first_trade_date` 是 Unix epoch 毫秒，固定按 UTC 解析，禁止依赖本机时区。
- 只接受 `currency == "HKD"`、`product_sub_category == "ETFs"`、严格正整数 `lot_size`，且目标必须
  精确全覆盖。
- 输出固定 `market=HK`、`instrument_type=ETF`、`status=LISTED`、`delist_date=null`，最终通过
  `InstrumentSchema`。

选择规则版本：`latest_trade_date_lte_as_of_v1`。

## 3. 文件白名单

- `src/quant/data/connectors/hkex_etp.py`
- `src/quant/data/connectors/__init__.py`
- `src/quant/data/mappers.py`
- `src/quant/data/pipeline.py`
- `src/quant/data/update_instruments.py`
- `tests/unit/test_hkex_etp_connector.py`
- `tests/unit/test_hkex_etp_instruments.py`
- `tests/unit/test_update_instruments.py`
- `README.md`
- 本任务及对应验证报告

## 4. 失败语义与禁止项

稳定错误码：

- `HKEX_ETP_TARGETS_INVALID`
- `HKEX_ETP_TOKEN_INVALID`
- `HKEX_ETP_FETCH_FAILED`
- `HKEX_ETP_JSONP_INVALID`
- `HKEX_ETP_RESPONSE_INVALID`
- `HKEX_ETP_ROW_INVALID`
- `HKEX_ETP_COVERAGE_INCOMPLETE`
- `HKEX_ETP_IDENTITY_CONFLICT`

禁止：

- 把 31 个 ETF 映射为 STOCK；
- 抓取全量 ETP 后不经显式目标约束直接写 clean；
- 选用晚于 `as_of` 的行或用抓取日替代 `trade_date`；
- 用浮点截断获得 board lot；
- 在 Tushare/BaoStock 路径静默忽略 HKEX 专属参数；
- 将 `02983.HK` 混入本任务。

## 5. 反例与验收

至少覆盖：动态 token 注释样例误选、callback/尾随垃圾、重复 JSON key、非有限数、失败 response、
future-only、缺目标、同日身份冲突、错误币种、非 ETF、零/浮点 lot、UTC 日期、raw 已写但 mapper 失败时
clean 不变、成功 upsert 不覆盖现有股票、CLI 参数在网络/写盘前 fail-fast、输出不含 token。

验证顺序：Windows 定向 pytest/Ruff/mypy 快速反馈；WSL Miniforge `base` 同组 Gate；一次精确 31 目标的
真实 HKEX smoke 与 raw SHA 闭包；再运行双 Route available-history Gate。完成 R2A 后若仍只缺
`02983.HK`，必须保留 `BAR_WINDOW_REFERENCE_INVALID`，不得提前宣布 Gate 通过。

完整证据见
[`M1_HK-INSTRUMENT-R2A_HKEX_ETP权威补全主Agent验证报告.md`](M1_HK-INSTRUMENT-R2A_HKEX_ETP权威补全主Agent验证报告.md)。
