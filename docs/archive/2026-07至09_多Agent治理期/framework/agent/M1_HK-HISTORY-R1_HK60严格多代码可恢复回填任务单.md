# M1 HK-HISTORY-R1 HK60 严格多代码可恢复回填任务单

日期：2026-07-18  
执行者：主 Agent（24 小时用户覆盖期内不调用外部 Cursor Agent）  
状态：真实执行中（1/8 batch PASS；后台单写者等待下一冷却点）

## 1. 目标与来源边界

以 2026-07-10 双 Route available-history Gate 的 613 只官方 STOCK、36,376 个精确应有
`(symbol, trade_date)` 为目标，完成 Tushare `hk_daily` source-closure raw 回填并在全批闭合后统一发布
clean。

本次显式选择 `MULTI_SYMBOL_RANGE_STRICT_V1`：P1 已实测逗号分隔两代码完整返回 60 日，但港股接口文档
没有明确承诺该语法。因此它只是一项有界加速，不是长期生产合同；文档化的按交易日全市场模式保留为未来
**新计划**的基线，当前计划不得静默切换。

目标拆分：

- P1 seed：`00005.HK/00700.HK` 共 120 个精确键，复用 snapshot
  `132620.624930Z-77c02bc1c1a8`，禁止重复请求。
- 明确未解决：`02983.HK` 仅需 2026-07-10 一键，但 P0 单日全市场已确认供应商缺失；本轮不重复消耗
  API，不借用 `02525.HK`，等待合规来源或后续显式契约。
- 剩余 610 只、36,255 个键按排序代码最多 80 只/批，共 8 批；所有 wire request 固定全局区间
  `2026-04-14..2026-07-10` 和 11 个字段。80×60=4,800，为 5,000 行上限保留 200 行余量。

## 2. 冻结架构

新增 HK 专用 core/CLI，不修改或耦合 M3-G1 请求合同：

- `src/quant/data/hk_history_backfill.py`：plan/request identity、journal、raw-first 执行、精确键验证与 finalize。
- `src/quant/data/backfill_hk_history.py`：一次调用最多执行一个新 API request 的 CLI。
- 复用 `RawStore.write_request/verify_request_bundle`、`hold_journal_writer_lock`、
  `TushareConnector.fetch_hk_daily_batch_raw`、`TushareBarMapper`、`Bar1dSchema`、`CleanBarStore`。
- plan/journal 只保存相对 POSIX selector，不绑定 Windows/WSL 绝对路径；同一 plan 固定 WSL writer，Windows
  只做定向测试，不与 WSL 并发写 journal。

plan 必须冻结：策略/版本、as-of、60 日历窗口、完整逐证券 expected dates、seed/unresolved、字段、批大小、
每批排序 symbols/wire 参数/request ID 与 plan SHA。已有 plan 只能逐字段验证，禁止覆盖漂移。

## 3. 状态机与 API 预算

1. 联网前写不可变 intent/attempt（UTC 时点）；跨进程读取所有 attempt 与 seed `fetched_at`，新调用距最近
   尝试不足 3,600 秒时稳定返回 `HK_HISTORY_COOLDOWN_ACTIVE`。
2. 每次 CLI 最多一个新请求；不自动 retry、分页、拆批或切换按日模式。
3. API 成功响应无论内容好坏都先写 deterministic request raw，再做离线验证；API 异常只写脱敏失败事实，
   不伪造空 raw。存在不确定 attempt 时，冷却后也必须显式确认才可重试同一 request。
4. 已有完整 PASS receipt 的批次只复验 raw，永不联网；raw 单边文件、metadata/hash 冲突均 fail closed，
   不自动修复或覆盖。
5. 全 8 批 PASS 与 seed 精确闭合前，禁止写任何 HK60 clean。全批闭合后再聚合映射、Schema、现有同键
   同值预检、一次 finalize、写后重读和双 Route Gate。

## 4. 精确失败语义

- 输入/plan/reference：`HK_HISTORY_INPUT_INVALID` / `HK_HISTORY_PLAN_CONFLICT` /
  `HK_HISTORY_REFERENCE_INVALID`。
- 限频/不确定尝试：`HK_HISTORY_COOLDOWN_ACTIVE` / `HK_HISTORY_ATTEMPT_UNCERTAIN`。
- API：`HK_HISTORY_API_FAILED`，不得包含供应商原文或 token。
- raw 内容：`HK_HISTORY_RAW_INVALID`；raw 必须保留，receipt 不得标 PASS。
- 全批未闭合：`HK_HISTORY_INCOMPLETE`；clean 字节保持不变。
- clean 同键异值或发布/写后核对失败：`HK_HISTORY_PUBLISH_CONFLICT` /
  `HK_HISTORY_PUBLISH_FAILED`。

## 5. raw 后对抗性 Gate

每批逐项要求：字段集合精确；`ts_code` 只含本批目标；每只证券日期集合精确等于 plan 的生命周期后应有
sessions；重复键（即使值相同）、空值、区间外/非开市/上市前日期、目标全缺/部分缺失、目标外证券、响应
达到或超过 5,000 行均失败。只在这些检查后逐行派生 `_request_symbol=ts_code` 与 `_market=HK`，再执行
HK-only OHLC mapper 和 `Bar1dSchema`；不得使用会先去重的通用 `fetch_bar_1d()`。

停牌日无行仍按当前 Gate 视为缺失，不合成零成交 bar；若要豁免，必须另立任务先引入权威停牌事实并修改
Gate SSOT。新上市短窗按 plan 精确 dates 验证，不按统一 60 行误判。

## 6. 验收

- 单元/集成：plan 稳定性、80 边界/8 批、逐证券短窗、seed/unresolved、request ID、全局 cooldown、每次最多
  一次 API、API 异常/不确定 attempt、raw-first invalid retained、重复/额外/缺失/5000 截断、receipt/hash
  篡改、全批前 clean 不变、existing clean 同值幂等/异值失败、finalize 重跑。
- WSL/Windows 定向 pytest 与 Ruff；WSL mypy。真实 API 与最终 Gate 只在 WSL Miniforge `base`。
- Tushare source closure 完成后预期双 Route 只剩 `02983.HK` 一键缺失；在取得该键合规来源前不得宣称
  全 36,376 键或 M1 HK60 Gate 通过。

已知限制：现有 `RawStore.write_request` 在 data/metadata 之间故障会留下 fail-closed 单边目录；现有
`CleanBarStore` 也不是跨 60 分区整体原子发布。本任务不虚称完全无人工恢复或全分区原子可见；任何单边 raw
需人工隔离，clean finalize 以幂等重跑、完成 receipt 与最终 Gate 收敛。若未来要求更强保证，另立不可变
bundle/release-pointer 任务，不在本次过度扩张 storage 架构。
