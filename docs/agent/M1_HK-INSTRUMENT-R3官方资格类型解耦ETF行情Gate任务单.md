# M1 HK-INSTRUMENT-R3 官方资格类型解耦 ETF 行情 Gate 任务单

日期：2026-07-18  
执行者：主 Agent  
状态：已完成（主 Agent 验证通过）

## 1. 目标与不变量

`ConnectEligibilitySnapshotSchema` 与 `ConnectEligibilityEventSchema` 已把官方资格事实中的
`security_type` 固定为 `STOCK/ETF/OTHER`。available-history Gate 却只依赖 Instrument 表判断 ETF，导致
仅为排除 ETF 而必须额外采集 HKEX 网页证券主表。R2A 许可撤回后，这个耦合成为不必要的 Gate 阻塞。

本任务让 Gate 优先消费已验证的官方资格类型；只有官方事实为 `OTHER`/缺失时才回退 Instrument。它不删除
Instrument 对股票上市日、退市日和身份的权威职责，也不改变 eligibility 或 universe 成员。

## 2. 冻结规则

- 显式传入 clean `connect_snapshot` 与 `connect_event` roots；只由 `quant.data` 读取。
- 每个文件分别通过 `ConnectEligibilitySnapshotSchema` / `ConnectEligibilityEventSchema`。
- HK 证券类型是全市场身份属性，可合并两条 Route 的非 `OTHER` 事实；同一 symbol 出现 STOCK/ETF 冲突时
  `BAR_WINDOW_REFERENCE_INVALID`。
- 官方类型为 ETF：直接从历史行情要求中排除；Instrument 行可缺失，但若存在且标成 STOCK 则冲突失败。
- 官方类型为 STOCK：仍必须存在 Instrument 且为 STOCK，用其 `list_date/delist_date` 计算精确应有交易日。
- 官方为 OTHER/缺失：必须存在 Instrument，并只接受 STOCK/ETF；不得猜测。
- 现有 31 个 ETF 的暂存 clean 不再是 Gate 分类所必需；本任务不删除历史 raw/clean，也不宣称其来源合规。

## 3. 反例与验收

- 官方 ETF、Instrument 缺行：合法排除，Gate 可通过。
- 官方 ETF、Instrument=STOCK：reference invalid。
- 官方跨 Route STOCK/ETF 冲突：reference invalid。
- 官方 STOCK、Instrument 缺行：reference invalid。
- 只有 OTHER 时按 Instrument 分类，保持既有行为。
- 613 STOCK 的上市后精确 sessions、`02983.HK` 一日结构性短历史语义不变。
- WSL/Windows 定向 pytest、Ruff 通过；WSL 定向 mypy 通过；重跑双 Route 真实 Gate。

验证证据见
[`M1_HK-INSTRUMENT-R3官方资格类型解耦ETF行情Gate主Agent验证报告.md`](M1_HK-INSTRUMENT-R3官方资格类型解耦ETF行情Gate主Agent验证报告.md)。
