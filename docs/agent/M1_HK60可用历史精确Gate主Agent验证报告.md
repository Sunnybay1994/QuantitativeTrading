# M1 HK60 可用历史精确 Gate 主 Agent 验证报告

日期：2026-07-18  
结论：**代码与兼容性验证通过；真实双 Route Gate 未通过，前置阻断为 36 个 eligible Instrument 缺失。**

> 后续修订（2026-07-18）：R3 已让 Gate 优先使用双 Route 官方资格事实的 `security_type`，因此官方 ETF
> 不再要求 Instrument 行；官方 STOCK 仍必须有 Instrument 生命周期。以下内容保留当时实现与验证事实，
> 现行契约以
> [`M1_HK-INSTRUMENT-R3官方资格类型解耦ETF行情Gate主Agent验证报告.md`](M1_HK-INSTRUMENT-R3官方资格类型解耦ETF行情Gate主Agent验证报告.md)
> 为准。

## 1. 实现结果

- 保持既有 `BarWindowCoverage`、`AuditedBarWindow`、`recent_for_universe_audited()`、
  `--require-full-window` 及其缺省 JSON 完全不变。
- 新增正交 `AvailableHistoryCoverage`、`AuditedAvailableHistoryBarWindow` 和 available-history 查询/审计入口。
- `--require-available-history` 只在显式启用时读取 HK clean 日历与 Instrument；按 `[list_date, as_of]`
  最后 N 个 HK 开市日逐证券比较精确日期集合。
- 合法 HK Instrument 明确标记的 ETF 才排除；当前 `SUSPENDED` 不减少 required sessions。
- 缺引用稳定失败 `BAR_WINDOW_REFERENCE_INVALID`；缺日或混入上市前/非开市日稳定失败
  `BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE`；两个 Gate 同时启用时保留原 full-window 失败优先级。
- CLI 只输出结构性短窗、缺失/意外日期计数与 ETF 清单；完整精确日期证据保存在不可变 coverage 对象中，
  避免真实 600+ 证券失败时输出数万条重复日期。

## 2. 对抗性验证

新增测试覆盖：

- 新股上市后仅有 2 个开市日、请求 N=3：full-window 为 false，但 available-history 为 true 并可写 output；
- 返回条数与 required 条数相同但用闭市日替换一个 required 日：同时报告 missing/unexpected 并拒绝写 output；
- 只有合法 Instrument `ETF` 才排除；ETF 外观代码缺 Instrument 仍 fail closed；
- `SUSPENDED` 股票缺一个 required 日仍失败；
- HK 日历自然日缺口归一为 reference invalid；
- 两个 Gate 同时指定且 full-window 不足时，仍先返回原 `BAR_WINDOW_INCOMPLETE`。

## 3. 验证命令与结果

Windows Miniforge base：

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_query_universe.py tests/unit/test_query.py -q
45 passed
D:\Miniforge3\python.exe -m ruff check src/quant/data/query.py src/quant/data/query_universe.py tests/unit/test_query_universe.py
All checks passed
D:\Miniforge3\python.exe -m mypy src/quant/data/query.py src/quant/data/query_universe.py
Success: no issues found
```

WSL Miniforge base：同一组 pytest 为 `45 passed`，Ruff 与 mypy 均通过。

真实只读 Gate（`as_of=2026-07-10`、`source=tushare`、`observations=60`）：

```text
SH_CONNECT -> BAR_WINDOW_REFERENCE_INVALID
SZ_CONNECT -> BAR_WINDOW_REFERENCE_INVALID
```

两次均未指定 `--output`、未联网、未修改 raw/clean/artifacts。结果与前置审计的 36 个 eligible Instrument
缺口一致，因此不能宣称 HK60 或 M1 Gate 通过。

## 4. 剩余风险与下一步

1. 需为 36 个成员取得可追溯的证券类型、上市日、board lot；31 个疑似 ETF 不能按代码猜测或伪装 STOCK。
2. 当前账号无 `hk_adjfactor` 权限；不复权 bar coverage 即使未来通过，也不等于港股复权收益链通过。
3. 没有逐日停牌历史 SSOT 前，Gate 会把停牌日无 bar 视为缺口；后续若引入停牌事实，必须先冻结来源、
   时间有效性和 exact-date 豁免契约，再修改本 Gate。
