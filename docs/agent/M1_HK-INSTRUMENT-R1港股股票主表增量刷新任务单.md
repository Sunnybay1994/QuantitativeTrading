# M1 HK-INSTRUMENT-R1 港股股票主表增量刷新任务单

日期：2026-07-18  
执行者：主 Agent（用户已授权后续 Tushare API 自行统筹）  
状态：已完成（2026-07-18；仅完成股票主表增量刷新，HK60 Gate 未通过）

## 1. 目标与依据

使用现有生产 `update_instruments --source tushare --market HK` 对 `hk_basic` 做一次有界增量刷新。Tushare
官方权限表说明 `hk_basic` 为 2000 积分接口、全部历史每日更新；现有 connector 按 L/D/P 三种状态各请求一次，
合计 3 次调用，低于账号档位频率。

当前 36 个 eligible Instrument 缺口已由 SSE 官方 2026-07-10 快照分类为 5 个 `股票`、31 个 `ETF`。
本任务只期望补齐可能已进入最新 `hk_basic` 的 5 个股票；`TushareInstrumentMapper` 不得把 31 个 ETF 映射为
STOCK，ETF 留给独立的 HKEX ETP 权威来源任务。

## 2. 边界与失败语义

- 运行前确认没有同类写进程；只运行一次生产 CLI，不并发、不循环重试。
- raw 必须通过 `RawStore` 不可变留档，clean 通过 `InstrumentSchema` 和既有原子 upsert。
- 不输出 token，不读取 `data/legacy/`，不修改 mapper 以迁就缺口。
- API/Schema/存储失败时保留 raw/错误证据并停止；先核对进程与权威状态再决定是否恢复。
- 验收只按新增的真实 Schema-valid HK Instrument 行；不以 API exit 0 单独宣布 Gate 通过。

## 3. 验收

1. 记录 snapshot id/raw path/clean rows，验证 raw metadata 与 SHA-256 闭包。
2. clean HK Instrument 全表通过 `InstrumentSchema`，并核对 5 个 SSE-证明股票的覆盖。
3. 再跑双 Route available-history Gate：若仍因 31 个 ETF 引用缺失返回
   `BAR_WINDOW_REFERENCE_INVALID`，视为本任务预期边界，不宣称 HK60 通过。

## 4. 执行结论

- 已按冻结命令执行一次 HK `hk_basic` 刷新，共 3 次状态请求（L/D/P），没有重试或扩大范围。
- 5 个候选股票中新增 4 个合法 Instrument：`00537.HK`、`01377.HK`、`06067.HK`、
  `06745.HK`。
- `02983.HK` 是 2026-07-10 因股份拆细启用的临时并行交易柜台，不属于 Tushare `hk_basic`
  普通股票主表的遗漏；不得伪造为普通新上市公司。
- 剩余引用缺口严格收敛为 31 个 ETF 与 `02983.HK`，真实 Gate 仍按预期返回
  `BAR_WINDOW_REFERENCE_INVALID`。后续由 HKEX 权威 ETP/新上市证券数据任务补齐。

完整证据见
[`M1_HK-INSTRUMENT-R1港股股票主表增量刷新主Agent验证报告.md`](M1_HK-INSTRUMENT-R1港股股票主表增量刷新主Agent验证报告.md)。
