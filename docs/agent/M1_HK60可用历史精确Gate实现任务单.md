# M1 HK60 可用历史精确 Gate 实现任务单

日期：2026-07-18  
执行者：主 Agent（用户 24 小时流程简化授权；不调用外部 Agent）  
状态：已实现并完成双平台定向验证；真实 Gate 因 Instrument 前置缺口按预期失败

## 1. 目标

在不改变既有 `BarWindowCoverage.is_full_window` 和 `--require-full-window` 行为的前提下，新增 opt-in
`--require-available-history` Gate。它按权威 HK 日历和证券上市区间审计每只有效港股通股票的精确应有交易日，
区分“上市不足 N 日”的合法短窗与真实数据洞。

## 2. 冻结契约

- eligible 集合仍由既有 `universe_membership` 与 `as_of` 决定。
- 每只 `STOCK` 的 required sessions 是 clean HK 日历中 `[list_date, as_of]` 范围内最后 N 个开市日；
  上市后不足 N 日时只要求全部可用历史。
- `ETF` 只有在唯一、合法的 HK `InstrumentSchema` 行明确证明类型为 `ETF` 时才排除；不得按代码或名称猜测。
- 当前没有可审计的历史停牌 SSOT，故 `status=SUSPENDED` 不减少 required sessions。
- 返回股票的观测日必须与 required sessions 精确相等；缺日和非开市/上市前等意外日期均失败，不能只比较计数。
- Instrument/日历文件缺失、Schema 非法、eligible Instrument 缺失、错市场、重复、未来上市、as_of 已退市、
  日历窗口不连续或不足以证明最后 N 个开市日，统一稳定失败 `BAR_WINDOW_REFERENCE_INVALID`。
- 精确日期集合不完整时返回 `BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE`，非零退出且不写 output。
- 两个 Gate 可同时指定，必须分别满足；不指定新参数时原 API、JSON payload 与 CLI 行为保持不变。

## 3. 文件白名单

- `src/quant/data/query.py`
- `src/quant/data/query_universe.py`
- `tests/unit/test_query_universe.py`
- `README.md`
- 本任务单和对应主 Agent 验证报告

## 4. 禁止项与反例

- 不修改 Schema/枚举，不引入新依赖，不读取 `data/legacy/`，不调用真实 API。
- 不用成员 `effective_from`、代码前缀、名称或当前交易所网页冒充 `list_date`/证券类型。
- 不因当前 Instrument 状态为 `SUSPENDED` 而豁免交易日。
- 对抗性反例：某证券返回两行且 required 也是两日，但其中一行是非开市日、另一 required 日缺失；计数相等仍必须失败。

## 5. 验收

1. 现有 CLI 三个测试保持通过且未启用新 Gate 时 payload 不变。
2. 覆盖新股合法短窗、ETF 显式排除、精确集合错位、缺 Instrument、停牌不豁免、引用日历非法及双 Gate 组合。
3. Windows `base` 与 WSL Miniforge `base` 定向 pytest、Ruff、mypy 均通过。
4. 对真实 2026-07-10 双 Route 只读执行新 Gate，预期因 36 个 Instrument 缺口以
   `BAR_WINDOW_REFERENCE_INVALID` 失败且不写候选产物；该结果不构成 M1 Gate 通过。
