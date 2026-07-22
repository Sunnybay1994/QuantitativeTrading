# M1 HK-HISTORY-P0 `hk_daily` 单次权限与响应探针任务单

日期：2026-07-18  
执行者：主 Agent  
状态：已执行；权限通过，响应覆盖与 Schema 契约未通过

## 1. 目标

用恰好一次 `hk_daily(trade_date=20260710)` 验证当前 Tushare 账号是否具备港股日线独立付费权限，以及
单日响应能否覆盖 2026-07-10 双 Route Gate 所需的 613 个股票代码。官方权限表把 `hk_daily` 列为
“1000 元”独立服务，不得把 2000 积分 `hk_basic` 权限等同于日线权限。

## 2. 冻结边界

- 目标集合直接从已验证的 available-history coverage `required_sessions` 派生，严格 613 个 STOCK；31 个 ETF
  已合法排除，不请求。
- 只请求 2026-07-10 一天；`TushareConnector` 的单日路径使用一次全市场 `hk_daily(trade_date=...)`，
  再在本地过滤目标。
- 成功响应写入独立不可变 raw 表 `tushare/hk_daily_access_probe`，metadata 只记录日期、目标数、目标集合
  SHA-256 和用途，不写 token 或完整目标清单。
- 不写 clean、不写质量报告、不请求复权因子；本任务只回答权限与响应结构，不宣布行情 Gate 通过。
- API 失败只记录稳定 `HK_DAILY_ACCESS_PROBE_FAILED` 和异常类型，不输出供应商原始异常文本或凭据。

## 3. 验收与后续分支

- 若成功：记录 snapshot id、raw SHA/行数、目标覆盖数、缺失数、字段和 Schema mapper 结果；再冻结按交易日
  批量回补设计，预计最多 60 次全市场日请求，不使用 613 次逐证券多日请求。
- 若权限拒绝：停止 Tushare HK60 回补，保留当前 Gate 状态，评估已授权且可留 raw 的替代权威数据源；
  不循环重试、不通过伪造/填充绕过。
- 若成功但有停牌缺行：必须显式保留缺口；后续 clean 发布与 exact-date Gate 的停牌语义另行冻结。

## 4. 执行结论

- 严格只调用一次 `hk_daily(trade_date=20260710)`，账号权限通过；未进行重试或追加 Tushare 请求。
- 不可变 raw snapshot 为 `122521.406613Z-f5b205dcd4e7`，612 行，SHA-256 为
  `3f9f163a4ec7e672a0eac6d13ab483e5ff8bc789f46126f6c69fc04a0b5615a2`。
- 613 个目标中覆盖 612 个，唯一缺失 `02983.HK`；该临时柜台不能被静默排除或伪造填充。
- mapper 后无重复键和空值，但 `02609.HK` 的供应商原始值为 `open=3.08`、`high=3.06`，不满足现行
  `Bar1dSchema` 的 `open <= high` 约束。因此没有写 clean，也没有宣布 HK60 Gate 通过。
- 后续先核实 HKEX 权威历史接口和该 OHLC 反例的交易语义；在证据冻结前不放宽 Schema，也不启动最多
  60 次、受 1 次/小时限频约束的逐交易日回补。

详细证据见
[`M1_HK-HISTORY-P0_hk_daily单次权限与响应探针主Agent验证报告.md`](M1_HK-HISTORY-P0_hk_daily单次权限与响应探针主Agent验证报告.md)。
